# CLAUDE.md — process-api

Service guide for `process-api`. It specializes the [root CLAUDE.md](../CLAUDE.md)
and wins wherever the two differ; everything the root file says still applies
unless overridden here.

## Service Overview

OGC API – Processes on pygeoapi (Flask), served by gunicorn on port 5000
(`expose:` only), with public prefix `/process-api`. Python 3.13 runtime; the
Dockerfile's `i18n` build stage compiles the catalogs.

| Process id | Processor | External source | Spec |
| --- | --- | --- | --- |
| `sentinel-fetch` | `eo_sentinel_fetch.py` | Copernicus openEO | [docs/SENTINEL_FETCH_PROCESS.md](docs/SENTINEL_FETCH_PROCESS.md) |
| `lidar-fetch` | `quebec_lidar_fetch.py` | Quebec MRNF LiDAR tiles | [docs/LIDAR_QUERY_SPECS.md](docs/LIDAR_QUERY_SPECS.md) |
| `weather-timeseries` | `weather_timeseries.py` | PAVICS THREDDS | [docs/CLIMATE_WEATHER_SPECS.md](docs/CLIMATE_WEATHER_SPECS.md) |
| `climate-timeseries` | `climate_timeseries.py` | PAVICS THREDDS (CMIP6) | same |
| `climate-indicators` | `climate_indicators.py` | PAVICS THREDDS | same |
| `msc-observations` | `msc_observations.py` | MSC GeoMet | [docs/MSC_OBSERVATIONS_QUERY_SPECS.md](docs/MSC_OBSERVATIONS_QUERY_SPECS.md) |
| `som-predict-soil` | `som_predict_soil.py` | local Parquet + PostGIS | [docs/SOM_PREDICT_SOIL_SPECS.md](docs/SOM_PREDICT_SOIL_SPECS.md) |
| `water-distance` | `water_distance.py` | PostGIS (GRHQ) | [docs/WATER_DISTANCE_SPECS.md](docs/WATER_DISTANCE_SPECS.md) |
| `som-field-match` | `som_field_match.py` | PostGIS | [docs/SOM_FIELD_MATCH_SPECS.md](docs/SOM_FIELD_MATCH_SPECS.md) |
| `pedo-coverage` | `pedo_coverage.py` | PostGIS (IRDA 2026, 2022) | [docs/PEDO_COVERAGE_SPECS.md](docs/PEDO_COVERAGE_SPECS.md) |

- Usage and examples: [README.md](README.md). openEO token:
  [docs/OPENEO_SETUP.md](docs/OPENEO_SETUP.md). Where these disagree with the
  code, trust the code, and fix the doc when you touch that area.
- Callers: the home map, the chatbot's `/sdss/query` loop (through
  `PYGEOAPI_INTERNAL_URL`) and direct API users.

## Common Commands

Run from the repo root.

```bash
make test-process-api       # Rebuilds the image, runs process_api/test/
make test-i18n              # agri_i18n tests — they run in this image
make test-repo-consistency  # /cog route guard — runs in this image with the repo mounted

# Single test — test/ is bind-mounted, so no rebuild needed for test edits
docker compose run --rm process-api pytest process_api/test/test_msc_observations.py -v

# Apply a change to processes/, config/*.yaml or requirements, then restart home
docker compose up -d --build process-api
docker compose restart home

# openEO refresh token (~30 days)
./process-api/scripts/get_openeo_token.sh
```

`processes/` and `config/pygeoapi-config.yaml` are baked into the image; only
`test/` and `config/openeo-config/` are mounted.

## Structure

```text
processes/
  wsgi.py                  gunicorn target: LocaleWSGIMiddleware(pygeoapi APP)
  config.py                Every env var, as pydantic-settings classes
  <process>.py             BaseProcessor subclass: validate → resolve → backend → output
  <process>_metadata.py    PROCESS_METADATA (pygeoapi schema, {"en", "fr"} texts)
  location_utils.py        resolve_location(): farm_id | point | bbox | polygon
  backend_utils.py         LocationValidatorMixin, variable conversions
  cache_utils.py           TTLCache shared by the PAVICS/MSC/CMIP backends
  asset_url_utils.py       Public COG / preview / TileJSON hrefs (see Outputs)
  jobs/                    schema (DDL), store (all job SQL), manager (pygeoapi), http (response rules)
  climate_backend/ weather_backend/ eo_backend/ lidar_backend/ som_backend/
config/
  pygeoapi-config.yaml     Server + process registry; ${HOST_*} filled by start.sh
  weather_datasets.yaml, climate_datasets.yaml   Dataset registries
  openeo-config/           Mounted; openEO client config
scripts/start.sh           envsubst → generate OpenAPI → validate env → gunicorn
test/                      Bind-mounted at /app/process_api/test; job_api.py and
                           job_processors.py are helpers for the job tests
```

`som_backend/research/` (notebook + README) is reference material, not
runtime code.

## Adding or Changing a Process

Follow an existing small processor (`msc_observations.py`) end to end:

1. **Input model.** Write a pydantic model in the backend package. Location
   inputs use `LocationValidatorMixin` plus `location_type`, `farm_id`,
   `point`, `bbox` and `polygon`, and go through `resolve_location()`.
2. **Processor.** In `execute()`:
   - validate with the model, and turn `ValidationError` into
     `ProcessorExecuteError(_("Invalid inputs: {errors}"))`;
   - re-raise `ProcessorExecuteError` as is;
   - log any other exception in English, then raise the generic translated
     `_("An unexpected error occurred while running this process.")`.
3. **Metadata.** Put it in `<process>_metadata.py`. Titles and descriptions are
   `{"en": …, "fr": …}` structs, not gettext.
4. **Registration.** Add a `resources:` entry in `pygeoapi-config.yaml` whose
   `processor.name` is the dotted class path.
5. **Docs and tests.** Add a spec in `docs/`, a row in the README table and in
   the table above, and tests.

Backends that call slow external services cache results in a module-level
`TTLCache`. Reuse it rather than adding another cache.

## Execution Model

- The pygeoapi manager is `processes.jobs.manager.AgriJobManager`, set under
  `server.manager` in `pygeoapi-config.yaml`. pygeoapi ignores a top-level
  `manager:` block.
- **Sync** (no `Prefer: respond-async`, or a process without `async-execute`):
  the process runs inline in the gunicorn worker exactly as under pygeoapi's
  `Dummy` manager: same outputs, failure body (`400`,
  `Error executing process: …`) and status. It writes no job row, so it does
  not depend on the database.
- **Async** (`Prefer: respond-async` on `sentinel-fetch`, `lidar-fetch` or
  `som-predict-soil`): the row is queued as `accepted` with the inputs and the
  request locale. The answer is `201` plus `Location`, and `process-worker`
  runs the job (see `processes/jobs/`). Declare `async-execute` in a
  process's `jobControlOptions` only if its outputs are JSON: async results
  are stored as `jsonb` in the job row.
- All job SQL lives in `processes/jobs/store.py`. Job rows are timestamped
  in pygeoapi's format; `/jobs` sorts on `started`, so it is set at
  submission.
- pygeoapi builds every served `jobControlOptions` from `manager.is_async`,
  not from the metadata, and adds `Location` to every execution answer.
  `processes/jobs/http.py`, installed on pygeoapi's Flask app in `wsgi.py`,
  restores each process's declared options, drops `Location` from non-`201`
  answers, and removes job-list links from the landing page (JSON and HTML)
  and from JSON process descriptions; HTML process pages keep pygeoapi's.
  pygeoapi's responses reach it without a mimetype, so it tries the body as
  JSON first.
- home nginx answers `404` to the public job list and `405` to any
  non-read method on `/process-api/jobs/…`. A job id is a capability link.
- gunicorn still runs **one sync worker** (compose sets neither
  `WEB_CONCURRENCY` nor `GUNICORN_TIMEOUT`), with a 600 s timeout. A long
  *sync* execution therefore still blocks every other request, so callers of
  the long processes should use async.
- Timeouts line up: gunicorn 600 s → home nginx `proxy_read_timeout 630s`.
  Caddy rate-limits `POST …/execution` (see `caddy/Caddyfile`).
- `start.sh` only substitutes `${HOST_PROTOCOL}` and `${HOST_URL}` in the
  config. Any other `${VAR}` in `pygeoapi-config.yaml` stays literal. Add a
  new variable to the `envsubst` list if you need it resolved.

## Configuration

- Read env only through the classes in `processes/config.py`. `start.sh`
  instantiates them at boot, so a missing `POSTGRES_PASS` stops the container
  rather than failing the first request.
- `FarmConfig` (`FARM_TABLE_NAME`, `FARM_GEOMETRY_COLUMN`, `FARM_ID_COLUMN`)
  drives `location_type=farm_id`. The table must exist. The `.env.example`
  value `public.my_farm_parcels` is a placeholder, and farm-id lookups fail
  until it names a real table.
- The database role is the app role (`DB_USER` mapped onto `POSTGRES_USER`).

## Outputs and Cross-Service Contracts

- `sentinel-fetch` and `lidar-fetch` write COGs to `/data` (the shared
  `data/output/raster_cog`). They publish STAC items to
  `sentinel2_eo_products` / `lidar_quebec` at `ApiConfig.STAC_API_URL`, which
  is internal (`http://stac-api:8081`). The public `/stac-api/` path is
  read-only and rejects writes with 403.
- Build every public href with `asset_url_utils.py`. `COG_ROUTE` is one of the
  four `/cog` copies guarded by `test/test_cog_route_consistency.py`, and
  `RASTER_API_DATA_DIR = "/data"` must match raster-api's mount (see
  [raster-api/CLAUDE.md](../raster-api/CLAUDE.md#the-url-contract)).
- `som-predict-soil` reads `BareSoil_TOPCLI_*.parquet` from `DUCKDB_DATA_DIR`
  (ingested by gis-pipeline). It caches trained models keyed by a fingerprint
  of those files (`som_model_store.py`). `get_or_train()` holds an `flock` on
  `som_model_<scenario>.lock` beside the bundle, so concurrent web and worker
  processes on the same host train a scenario once. Keep every bundle read
  and write inside that lock.
  - Callers send `som_field_boundaries.gid`; the process translates it to the
    GEE `FIELD_ID` through `gee_field_id`, which gis-pipeline stamps. The two
    identifiers differ, so never compare them directly.
  - `som-field-match`, and `som-predict-soil` given a location, rank fields by
    `som_field_boundaries.has_gee_data`, which gis-pipeline stamps at the end
    of each run.
  - Known fields are served field-grouped cross-validated predictions, never
    out-of-bag ones. Bump `BUNDLE_FORMAT_VERSION` whenever cached bundles
    become wrong to serve.

## Internationalization

- `wsgi.py` wraps pygeoapi in `LocaleWSGIMiddleware`, because pygeoapi never
  passes its negotiated locale to `execute()`. `lang` and `Accept-Language`
  both work.
- `ProcessorExecuteError` messages and pydantic validator messages go through
  `_()`, with literal msgids and `.format()`. Process titles and descriptions
  use the `{"en", "fr"}` metadata structs.

## Logging

- Use stdlib `logging` with lazy `%s`, as most of the code does. The remaining
  f-string log calls (about a dozen) are debt; convert them on lines you touch.
- pygeoapi's own logging is set to `DEBUG` into `/tmp/pygeoapi.log` inside the
  container (`pygeoapi-config.yaml`). It is not visible in
  `docker compose logs`.

## Testing

- The suite is `unit` and `mocked`, with one exception. openEO
  (`openeo.connect`), THREDDS, GeoMet, LiDAR downloads, `requests` and
  `psycopg` are always patched, and a test must never reach a real external
  service.
- The exception is the job store and queue: `test_jobs_*_integration.py`
  (`integration`) run against the live database. Each test creates a
  throwaway `zz_it_jobs_*` table and drops it afterwards, and the module skips
  when PostgreSQL is unreachable. `SKIP LOCKED` claims and advisory-lock crash
  detection cannot be mocked. Keep every other database access patched.
- Tests import `processes.<module>`. Inside `processes/`, prefer relative
  imports; `asset_url_utils.py` is the one module using
  `from processes.config import …`.
- Keep the pattern of one `test_<process>.py` per processor. Cover validation
  errors (translated, French by default), the backend-failure wrap, and a
  happy path with a mocked backend.
- `test_cog_route_consistency.py` needs the whole repo. It skips itself in
  `make test-process-api` and really runs only through
  `make test-repo-consistency`.
