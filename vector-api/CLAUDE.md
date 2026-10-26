# CLAUDE.md — vector-api

Service guide for `vector-api`. It specializes the [root CLAUDE.md](../CLAUDE.md)
and wins wherever the two differ; everything the root file says still applies
unless overridden here.

## Service Overview

OGC API – Features over two backends, plus the `/pedo-properties` utility
endpoint, in one FastAPI app on port 8083 (`expose:` only). Public prefix:
`/vector-api`.

| Route | Backend | Code |
| --- | --- | --- |
| `/postgis/*` | PostGIS via TiPg (mounted sub-app) | `app.py` |
| `/parquet/*` | GeoParquet via DuckDB | `parquet_router.py`, `duckdb_manager.py` |
| `POST /pedo-properties` | PostGIS overlap + GeoParquet joins | `pedo_properties_router.py`, `db_pool.py` |
| `POST /parquet/collections/{id}/invalidate` | DuckDB cache | `parquet_router.py` |

The water-distance, pedo-coverage and som-field-match utilities are OGC
processes in process-api, not vector-api routes; see
[process-api/CLAUDE.md](../process-api/CLAUDE.md).

- Endpoint list, output formats, configuration:
  [README.md](README.md). Where it or
  [docs/vector_endpoint.md](docs/vector_endpoint.md) disagree with the code,
  trust the code, and fix the doc when you touch that area.
- Callers: the home map (`frontend/home`), the chatbot (`VECTOR_API_URL`), and
  gis-pipeline (the `/invalidate` notification).

## Common Commands

Run from the repo root.

```bash
make test-vector-api      # Rebuilds the image, runs the suite

# Single test — test/ is bind-mounted, so no rebuild needed for test edits
docker compose run --rm vector-api pytest vector_api/test/test_parquet_endpoints.py -v

# Apply a src/ change to the running stack (src/ is baked into the image)
docker compose up -d --build vector-api
docker compose restart home   # home nginx caches the old container IP → 502s
```

Restart `home` after recreating `vector-api` — see the root
[Ops](../CLAUDE.md#ops) note.

## Structure

```text
src/                      Copied to /app/vector_api — import as the vector_api package
  app.py                  FastAPI app, lifespan (TiPg DB init with 5 retries),
                          MountRootPathMiddleware, landing + Parquet OpenAPI routes
  config.py               Prefixes, CORS, APP_ROOT_PATH → EXTERNAL_ROOT,
                          external_base_url()
  parquet_router.py       /parquet OGC Features routes + /invalidate
  duckdb_manager.py       DuckDBManager singleton: discovery, schema cache,
                          materialized connections, queries
  materialize.py          RTree-indexed .duckdb build (copy — see Cross-Service)
  db_pool.py              asyncpg pool for pedo_properties_router
  pedo_properties_router.py   /pedo-properties
test/                     Bind-mounted at /app/vector_api/test
scripts/entrypoint.sh     Waits for the database, then execs uvicorn
```

The image is `ghcr.io/developmentseed/tipg`, currently Python 3.14. Inside
`src/`, use relative imports (`from .config import …`); tests import
`vector_api.<module>`.

## URLs and Mounting

- Every href must include the public prefix. Build it with
  `external_base_url(request)` from `config.py`; never emit
  `request.base_url` directly.
- TiPg is mounted at `/postgis` through `MountRootPathMiddleware`. It sets
  `root_path` to the mount prefix and rewrites JSON response bodies to insert
  `APP_ROOT_PATH`. Widening `root_path` instead breaks TiPg routing (404).
- Home nginx strips `/vector-api/` and also `sub_filter`s the Swagger HTML. A
  new HTML page may need a matching rule in `frontend/home/scripts/entrypoint.sh`.
- `config.py` sets `TIPG_NAME` / `TIPG_ROOT_PATH` defaults, but `app.py`
  imports TiPg first, so they have no effect: the `/postgis` landing title is
  TiPg's default. Set TiPg options through `docker-compose.yml` env instead
  (as `TIPG_FALLBACK_KEY_NAMES` and `TIPG_DB_SPATIAL_EXTENT` are).

## Parquet Backend

- Collections are discovered on every request: each `*.parquet` in
  `DUCKDB_DATA_DIR` is a collection whose id is the file stem.
- `get_parquet_path()` is the only way to turn an id into a path. It enforces
  `COLLECTION_ID_PATTERN` and a resolve-inside-`data_dir` check against path
  traversal.
- ID column: first of `gid`, `id`, `fid`, `ogc_fid`, `objectid`. Geometry
  column: first of `geometry`, `geom`, `the_geom`, `shape`, `wkb_geometry`.
  Without an ID column, item ids are 1-based row numbers.
- A `<id>.duckdb` next to the Parquet file (built by gis-pipeline) is
  preferred automatically. It is opened read-only and cached per collection,
  and a file that fails to open is remembered and skipped.
  `invalidate_materialized()` clears both.
- The schema cache (`_schema_cache`) is never cleared. The code assumes
  Parquet files are immutable, but gis-pipeline overwrites `<id>.parquet` on
  re-ingestion, so feature count, bbox and detected columns stay stale until a
  restart. `/invalidate` does not clear it.
- DuckDB connections are not thread-safe. Every query goes through
  `_fetchone`/`_fetchall` with the matching lock. For a materialized
  connection, hold its lock across count and select, as `query_items()` does,
  so `/invalidate` cannot close it mid-request.
- SQL: escape identifiers with `escape_identifier()` and path literals with
  `_escape_sql_string()`. Bind values as `$1` parameters, never
  interpolation. `bbox` values are floats parsed and range-checked in the
  router before they reach SQL.

## The `/pedo-properties` Endpoint

- The polygon table comes from `PEDO_POLYGON_TABLE_NAME` (set in
  `docker-compose.yml`) and is interpolated into SQL. It is operator config,
  never request input.
- The GeoJSON input is always bound as `$1`, and the overlap query filters with
  `ST_Intersects` so the GiST index is used; keep that when editing it.
- The database role is the app role (`DB_USER` mapped onto `POSTGRES_USER`),
  so queries are read-only DML.
- It is a mixed endpoint: PostGIS only computes which IRDA polygons the
  parcel overlaps and by how much; the component, hydrologic-group and
  bulk-density joins run in DuckDB on the GeoParquet tables named by the
  `PEDO_*_COLLECTION` variables, through
  `DuckDBManager.parquet_source()` / `query_rows()`. Missing tables return 503.
- The IRDA `couverture_pps` table currently lacks every `numero_composante = 1`
  row (each polygon's dominant soil), so `described_pct` is low and the dominant
  hydrologic group can be wrong until it is re-imported. The endpoint reports
  the gap rather than hiding it; do not rescale `share_pct` to 100.

## Cross-Service Coupling

- `materialize.py` is duplicated in
  `gis-pipeline/src/gis_pipeline/modules/db/materialize.py`. The SQL and
  `MATERIALIZED_TABLE_NAME` must stay identical. There is no consistency test
  yet, so check the other copy by hand.
- The `/invalidate` route is the contract gis-pipeline calls after rebuilding
  `<id>.duckdb`. Do not rename it without changing
  `materialize_trigger.py`.
- `/invalidate` is reachable without authentication through the public proxy.
  It is idempotent and only forces a reopen, but do not add anything
  destructive behind it.

## Internationalization

- `LocaleASGIMiddleware` wraps the whole app, TiPg included.
- Translate 4xx validation and not-found `detail`s with `_()`, using literal
  msgids plus `.format()`. The 500 `"Internal server error"` detail is already
  translated; follow the existing pattern.
- `DuckDBManager` raises plain English exceptions. The router maps them to
  translated `HTTPException`s, so translate at the router, not in the manager.

## Logging

- Follow the root rule: stdlib `logging`, lazy `%s`. The utility routers do
  this. Much of `app.py`, `duckdb_manager.py` and `parquet_router.py` uses
  f-strings in log calls; that is debt, so convert it only on lines you touch.
- `app.py` calls `logging.basicConfig` at import; do not add another.

## Testing

| Marker | Where | What it needs |
| --- | --- | --- |
| `unit` / `mocked` | most files | nothing live; asyncpg pool and `requests` are patched |
| `integration` | `test_parquet_ogc_compliance.py` | real DuckDB on fixture GeoParquet (`tmp_path`) |
| `integration` | `test_postgis_integration.py` | live PostgreSQL; skips itself if unavailable |

- Build Parquet fixtures with the `sample_geoparquet` and `temp_parquet_dir`
  fixtures in `conftest.py`.
- Do not touch the real singleton. Patch
  `vector_api.parquet_router.get_shared_manager` to return a
  `DuckDBManager(data_dir=tmp_path)`, as `conftest.py` does.
- New utility endpoints need tests for the normal result, the empty result, a
  missing geometry (422) and a database error (500). Follow
  `test_pedo_properties_router.py`.
