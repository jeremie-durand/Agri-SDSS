#!/usr/bin/env python3
"""
Rebuild public.grhq_water_union — a single PostGIS table merging all eligible
line and polygon features from the Géobase du réseau hydrographique du Québec
(GRHQ). This union table is the data source for "distance from water" spatial
queries in the SOM Calculator.

Run this script manually after loading new GRHQ data into PostGIS. It inserts
rows in batches of 5 000 to avoid OOM and WAL overflow on large datasets, with
each batch committed independently. When done, follow the printed instructions
to atomically swap the new table into place and create the GiST spatial index.
"""

import os
import sys

import psycopg

BATCH_SIZE = 5_000

CONN_STR = (
    f"host={os.environ.get('POSTGRES_HOST', 'database')} "
    f"port={os.environ.get('POSTGRES_PORT', '5432')} "
    f"dbname={os.environ.get('POSTGRES_DBNAME', 'agri_sdss')} "
    f"user={os.environ.get('POSTGRES_USER', 'agri_sdss')} "
    f"password={os.environ['POSTGRES_PASS']}"
)

ELIGIBLE_TABLES_SQL = """
SELECT f_table_name
FROM geometry_columns
WHERE f_table_schema = 'public'
  AND f_table_name LIKE 'grhq_%'
  AND f_table_name NOT LIKE '%_rh_j%'
  AND f_table_name NOT LIKE '%junctions%'
  AND f_table_name NOT LIKE '%_c_hyd_p'
  AND f_table_name NOT LIKE '%_rh_r'
  AND f_table_name NOT LIKE '%_udh'
  AND f_table_name NOT LIKE 'grhq_water_union%'
  AND type NOT LIKE '%POINT%'
ORDER BY f_table_name;
"""

SETUP_SQL = """
DROP TABLE IF EXISTS public.grhq_water_union_new CASCADE;
CREATE TABLE public.grhq_water_union_new (
    id BIGSERIAL PRIMARY KEY,
    geometry GEOMETRY(GEOMETRY, 4326),
    source_table TEXT
);
"""


def insert_batch(table: str, offset: int) -> int:
    """Insert one batch from table at the given offset. Returns rows inserted."""
    sql = f"""
    INSERT INTO public.grhq_water_union_new (geometry, source_table)
    SELECT ST_Force2D(geometry), '{table}'
    FROM public.{table}
    ORDER BY ctid
    LIMIT {BATCH_SIZE} OFFSET {offset};
    """
    with psycopg.connect(CONN_STR) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            count = cur.rowcount
        conn.commit()
    return count


def main() -> None:
    with psycopg.connect(CONN_STR, autocommit=True) as conn:
        print("Setting up grhq_water_union_new table...", flush=True)
        with conn.cursor() as cur:
            cur.execute(SETUP_SQL)
        print("Table created.", flush=True)

        with conn.cursor() as cur:
            cur.execute(ELIGIBLE_TABLES_SQL)
            tables = [row[0] for row in cur.fetchall()]

    print(f"Found {len(tables)} eligible tables.", flush=True)

    total_inserted = 0
    for i, table in enumerate(tables, 1):
        with psycopg.connect(CONN_STR, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) FROM public.{table};")
                row_count = cur.fetchone()[0]

        if row_count == 0:
            print(f"  [{i}/{len(tables)}] {table}: empty, skipping", flush=True)
            continue

        batches = (row_count + BATCH_SIZE - 1) // BATCH_SIZE
        print(
            f"  [{i}/{len(tables)}] {table}: {row_count:,} rows, {batches} batch(es)",
            flush=True,
        )

        for batch_idx in range(batches):
            offset = batch_idx * BATCH_SIZE
            try:
                inserted = insert_batch(table, offset)
                total_inserted += inserted
                print(
                    f"    batch {batch_idx + 1}/{batches} +{inserted} rows (total={total_inserted:,})",
                    flush=True,
                )
            except Exception as e:
                print(
                    f"    ERROR batch {batch_idx + 1} offset={offset}: {e}",
                    file=sys.stderr,
                    flush=True,
                )
                sys.exit(1)

    print(f"\nPopulation complete. Total rows: {total_inserted:,}", flush=True)
    print("\nNext steps (run manually):", flush=True)
    print("  1. DROP TABLE IF EXISTS public.grhq_water_union;", flush=True)
    print(
        "  2. ALTER TABLE public.grhq_water_union_new RENAME TO grhq_water_union;",
        flush=True,
    )
    print(
        "  3. CREATE INDEX CONCURRENTLY grhq_water_union_geom_idx ON public.grhq_water_union USING GIST(geometry);",
        flush=True,
    )


if __name__ == "__main__":
    main()
