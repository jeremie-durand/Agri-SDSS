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
  app.py                  FastAPI app, lifespan (TiPg DB init with 5 retries,
                          background schema warm-up), MountRootPathMiddleware,
                          landing + Parquet OpenAPI routes
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
  `root_path` to the mount prefix and rewrites JSON and HTML response bodies to
  insert `APP_ROOT_PATH` (tiles and images pass through). The rewrite needs
  uncompressed bodies, which home's `Accept-Encoding ""` guarantees. Widening `root_path` instead breaks TiPg routing (404).
  It also points `scope["router"]` at TiPg's router: TiPg's landing resolves
  `request.url_for("openapi")` / `("swagger_ui_html")`, which on the parent
  router become `/postgis/openapi.json` and `/postgis/docs` (404).
- Home nginx strips `/vector-api/`, `sub_filter`s the Swagger HTML, and
  rewrites Starlette's slash-redirect `Location` back under `/vector-api/`
  (`proxy_redirect`). A
  new HTML page may need a matching rule in `frontend/home/scripts/entrypoint.sh`.
- `/parquet/openapi.json` is generated from `parquet_router.routes`, so a
  route added to that router appears in `/parquet/api.html` automatically; a
  route defined in `app.py` (the `/parquet` landing) does not. Do not build it
  by filtering `app.routes`: since FastAPI 0.141 an included router is a
  single `_IncludedRouter` entry there, and the spec came back empty (#276).
- `config.py` sets `TIPG_NAME` / `TIPG_ROOT_PATH` defaults, but `app.py`
  imports TiPg first, so they have no effect: the `/postgis` landing title is
  TiPg's default. Set TiPg options through `docker-compose.yml` env instead
  (as `TIPG_FALLBACK_KEY_NAMES`, `TIPG_DB_SPATIAL_EXTENT` and
  `TIPG_DB_FUNCTIONS` are).
- `TIPG_DB_FUNCTIONS=[]` keeps SQL functions out of the `/postgis` catalog.
  Without it TiPg lists every geometry-returning function in `public`,
  PostGIS's own included, and their items pages answer 422 (#277). To publish
  a project function, list it by `schema.name`; do not remove the setting.
- CORS belongs to the parent app alone (`VECTOR_API_CORS_ORIGINS`). `app.py`
  removes TiPg's own `CORSMiddleware`, which would otherwise reflect any
  origin on `/postgis/*` with `allow-credentials: true`. Home nginx adds no
  CORS header on `/vector-api/`.

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
  preferred automatically. It is opened read-only, and a file that fails to
  open is remembered and skipped. `invalidate_materialized()` clears both.
- Without its `.duckdb`, a collection is served from `read_parquet()`, about
  50× slower on large ones (#282). The first raw fallback of a geometry
  collection larger than `VECTOR_API_RAW_PARQUET_WARN_MB` (default 50) logs
  `Serving <id> from raw Parquet (<size> MB, no .duckdb)` once per process;
  `/invalidate` re-arms it. `_warn_if_large_raw_parquet()` is called where
  `query_items()` and `get_item_by_id()` fall back, not in
  `_run_materialized()`: `query_items()` skips that call when the file is
  missing. Collections without geometry can never be materialized and are
  never reported.
- Open `.duckdb` connections form an LRU capped by
  `VECTOR_API_MAX_OPEN_DUCKDB` (default 2). Each one is a separate DuckDB
  instance that keeps its own block cache, so an unbounded cache got the
  container OOM-killed after about 40 collections (#288). On the real data in
  1 GiB, cap 4 at 819MB was still killed and cap 2 walks all 253 collections.
  Raise the cap only together with the container memory. The cap bounds the
  cache, not every open instance: a new connection opens before the oldest is
  popped, and a popped one stays open until its running query ends, so up to
  `max_open + max_queries + 1` instances can be live for a moment. Openers stay
  one at a time: connections open under `_cache_lock`, and the request gate
  (below) admits one request.
- The lifespan starts `warm_schema_cache()` (`duckdb_manager.py`) as a
  background task once TiPg is up, and cancels it on shutdown. It creates the
  manager, then computes each collection's schema through
  `run_duckdb_request`, one collection per gate acquisition. The gate wakes
  waiters in arrival order, so a request that arrives mid warm-up waits for
  one scan, not the whole catalog. Do not fold the loop into a single
  `run_duckdb_request` call, and do not run it outside the gate. Failures are
  logged and never raised: start-up and `/postgis` never depend on it. On
  the 253 real collections (1 CPU) it takes 16–17 s, as long as the cold
  first `/parquet/collections` did (16.9 s; now about 15 ms). Stopping the
  container mid warm-up shuts down in about 0.1 s.
- The schema cache (`_schema_cache`) is never cleared. The code assumes
  Parquet files are immutable, but gis-pipeline overwrites `<id>.parquet` on
  re-ingestion, so feature count, bbox and detected columns stay stale until a
  restart. `/invalidate` does not clear it. A schema whose bbox scan raised
  (for example `OutOfMemoryException` under a low `DUCKDB_MEMORY_LIMIT`) is
  not cached: that request serves the collection without an extent, and the
  next one computes the schema again. This applies to any DuckDB error, so a
  bbox scan that always fails (a `geometry` column that is not a geometry
  type) is re-run and logged on every request for that collection.
- DuckDB connections are not thread-safe. In-memory queries go through
  `_fetchone`/`_fetchall`, which hold `self._lock`. Materialized queries go
  only through `_run_materialized(collection_id, work)`; never use the pair
  `_get_materialized_connection()` returns directly, because eviction or
  `/invalidate` can close it at any time. `_run_materialized` takes a query
  slot (`VECTOR_API_MAX_DUCKDB_QUERIES`, default 1), then the connection's
  lock, for the whole of `work`. It reopens a connection closed between lookup
  and lock. Run count and select in one `work`, as `query_items()` does.
- Lock rules that keep this deadlock-free:
  - `_cache_lock` guards only the cache dicts, including the identity check
    `_run_materialized` makes while holding a connection lock.
  - A connection is popped from the cache under `_cache_lock`, and then closed
    under its own lock with `_cache_lock` released. Never hold `_cache_lock`
    while waiting for a connection lock.
  - Order: query slot, then connection lock.
  - `self._lock` is separate: it is held for whole in-memory queries.
- Every request-time DuckDB call goes through
  `await run_duckdb_request(func, *args)` (`duckdb_manager.py`). It runs `func`
  in a worker thread behind one process-wide `CapacityLimiter(1)`, so DuckDB
  never blocks the event loop (#280) and one request at a time runs DuckDB
  work, on the in-memory and the materialized connections alike. That keeps
  the memory envelope the 819MB figure below and the cap figures above were
  measured with: `/postgis` and `/` stay responsive, and Parquet requests still
  queue behind each other. A waiting request holds no thread. Calling the
  manager directly from an `async def` route stalls the whole app again. A
  plain `def` route or `run_in_threadpool` skips the gate, so response
  rendering, feature building and in-memory vs materialized queries run in
  parallel outside that envelope. The query slots alone still serialize
  materialized queries: four parallel heavy queries were OOM-killed before
  they existed.
- The `/parquet` read routes are thin `async def` handlers. Each one keeps its
  signature and docstring, which feed `/parquet/openapi.json`, and passes a
  `_*_body` builder to `_render`. Rendering happens in the worker through
  `_json_response`, the same Pydantic JSON-mode serialization FastAPI used, so
  decimals stay strings and dates ISO. `response_model=dict[str, Any]` on the
  decorator keeps the OpenAPI schema. `test_parquet_response_encoding.py` and
  the snapshot in `test/data/parquet_openapi.json` pin both.
- `/invalidate` runs in the default thread pool, outside the gate. It runs no
  query, but it waits for a running query on the same collection, and
  gis-pipeline calls it with a 10 s timeout, so it must not queue behind other
  collections.
- Every DuckDB connection is opened with `config={"memory_limit": ...}` from
  `DUCKDB_MEMORY_LIMIT` (default `819MB`). The limit is per DuckDB instance,
  not per process: the in-memory connection and each materialized `.duckdb`
  are separate instances with their own budget. A connection opened without it
  defaults to 80% of the container memory, and a heavy query then gets the
  process OOM-killed instead of raising (#279).
- 819MB is sized for the largest single feature. `grhq_hr_06aa_udh` and
  `grhq_hr_06ac_udh` are each one polygon of about 56 MB of GeoJSON. They
  answer 500 at 512MB, and 200 at 819MB, with an HTTP peak of about 800 MB in
  1 GiB. The default memory settings and the cap were measured as a set:
  `make test-repo-consistency` checks that the compose defaults match the
  `DEFAULT_*` constants. Heavy queries spill to `<id>.duckdb.tmp` next to the
  data, which needs the read-write `./data/duckdb` mount.
- The `spatial` extension is installed at image build into
  `/tmp/.duckdb/extensions` (`HOME=/tmp`), owned by UID 1000, so a new
  container loads it without network access (#281). The run-time
  `INSTALL spatial` calls stay as a no-op fallback for running outside the
  image. Never mount a volume or `tmpfs` over `/tmp`: it would hide the
  extension, and the manager would download it again, or fail to start
  offline. `test_duckdb_extensions.py` fails if the extension was not baked
  into the image.
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
  Those joins run in `_load_soil_tables` through `run_duckdb_request`, the
  same gate as `/parquet`. The asyncpg overlap query stays on the event loop.
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
| `integration` | `test_parquet_ogc_compliance.py`, `test_parquet_catalog_walk.py`, `test_parquet_response_encoding.py`, `test_event_loop_isolation.py`, `test_parquet_schema_cache.py`, `test_schema_warmup.py` | real DuckDB on fixture GeoParquet (`tmp_path`) |
| `integration` | `test_duckdb_extensions.py` | the vector-api image, with `spatial` installed at build; fails outside it |
| `integration` | `test_postgis_integration.py` | live PostgreSQL; skips itself if unavailable |

- Build Parquet fixtures with the `sample_geoparquet` and `temp_parquet_dir`
  fixtures in `conftest.py`.
- Do not touch the real singleton. Patch
  `vector_api.parquet_router.get_shared_manager` to return a
  `DuckDBManager(data_dir=tmp_path)`, as `conftest.py` does.
- A session-scoped autouse fixture in `conftest.py` replaces
  `vector_api.app.warm_schema_cache` with a no-op, because the test container
  bind-mounts the real data. Keep it session-scoped: a session-scoped
  `TestClient` enters the lifespan before any function-scoped patch exists,
  and the real warm-up then holds the gate and stalls later tests. To test the
  warm-up itself, patch `vector_api.duckdb_manager.get_shared_manager`, as
  `test_schema_warmup.py` does.
- New utility endpoints need tests for the normal result, the empty result, a
  missing geometry (422) and a database error (500). Follow
  `test_pedo_properties_router.py`.
