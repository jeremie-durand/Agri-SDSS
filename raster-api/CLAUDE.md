# CLAUDE.md — raster-api

Service guide for `raster-api`. It specializes the [root CLAUDE.md](../CLAUDE.md)
and wins wherever the two differ; everything the root file says still applies
unless overridden here.

## Service Overview

The stock TiTiler application (`ghcr.io/developmentseed/titiler:2.4.0`, Python
3.14) plus a single custom route: `GET /collections`, which lists the COG files
on disk. It runs on port 8082 (`expose:` only), with public prefix
`/raster-api`.

- It renders COGs on demand: tiles, previews, info, statistics and point values
  under `/cog/*`. It also serves TiTiler's `/stac`, `/mosaicjson`, `/zarr`,
  `/tileMatrixSets`, `/colorMaps` and `/algorithms` groups. There is **no WMS
  or WCS** endpoint. The OpenAPI document at `/raster-api/api` is the full route
  list.
- It has no database and no state. It reads `.tif` files from
  `/data` (`./data/output/raster_cog`, mounted read-write).
- Usage, endpoints and configuration: [README.md](README.md) and
  [docs/raster_endpoint.md](docs/raster_endpoint.md). Where they disagree with
  the code or the live `/api`, trust those, and fix the doc when you touch that
  area.

## Common Commands

Run from the repo root.

```bash
make test-raster-api      # Rebuilds the image, runs the suite with coverage

# Single test — test/ is bind-mounted, so no rebuild needed for test edits
docker compose run --rm raster-api pytest raster_api/test/test_collections_endpoint.py -v

# Apply a src/ change (src/ is baked into the image), then restart home
docker compose up -d --build raster-api
docker compose restart home
```

## Structure

```text
src/                     Copied to /app/raster_api — import as the raster_api package
  main.py                Imports TiTiler's app singleton and adds collections_router
  collections_router.py  GET /collections: *.tif / *.tiff in RASTER_COG_DIR
test/                    Bind-mounted at /app/raster_api/test
scripts/entrypoint.sh    Waits for the database, then execs uvicorn
.coveragerc              Coverage scoped to raster_api, tests omitted
```

## How It Is Built

- `main.py` mutates `titiler.application.main.app` in place. It does not wrap
  or copy it, so TiTiler's routes, middleware and OpenAPI entries stay as they
  are. Extend the same way: add a router in `src/` and `include_router` it.
  Do not fork TiTiler's factories.
- TiTiler behaviour, TiTiler settings and the TiTiler version come from the
  base image tag. `requirements-raster-api.txt` only pins `numpy` and
  `rasterio`. A base-image bump can change routes. `test_raster_app_routes.py`
  guards the paths the frontend calls (`/cog/info`, `/cog/statistics`,
  `/cog/tiles`, `/collections`).
- uvicorn runs with `--root-path ${APP_ROOT_PATH}` (`/raster-api`), so
  TiTiler's self-links, TileJSON tile URLs and Swagger carry the public
  prefix. Keep `APP_ROOT_PATH` set in `docker-compose.yml`.
- Home nginx proxies `/raster-api/` to this service. The home map's offline
  service worker caches tiles only under `/raster-api/`.
- The entrypoint waits for PostgreSQL and the service has `POSTGRES_*` env,
  but nothing in the app uses the database. Do not add a database dependency
  here; COG metadata lives in PostGIS via gis-pipeline.

## The `url` Contract

Every render href published in STAC points here as
`/raster-api/cog/<endpoint>?url=/data/<file>.tif`. The `/data` part is this
container's mount path, and it is hard-coded as `RASTER_API_DATA_DIR = "/data"`
in two places:

- `gis-pipeline/src/gis_pipeline/core/config.py`
- `process-api/processes/asset_url_utils.py`

Renaming the mount, or the `RASTER_COG_DIR` default in `collections_router.py`,
breaks every published preview and TileJSON href. Unlike `/cog`, no consistency
test guards this; change all three places together.

- COG producers: gis-pipeline (`*_cog.tif`) and process-api (LiDAR and
  Sentinel-2 outputs). Both write to `./data/output/raster_cog`. The same
  folder also holds non-COG files (`*.stac.json`, `duckdb/`), which
  `/collections` ignores by extension.
- `bidx` and `rescale` are chosen by the publishers, not here. Rendering rules
  are in [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md#stac-asset-hrefs).
- `GET /collections` returns `{id, title}` from the file stem. It is read by
  `frontend/home/html/js/data-catalog.js`, so keep that shape.

## Security

- TiTiler opens whatever `url` it is given, and GDAL can follow remote schemes
  (`/vsicurl/`, `http(s)://`, `s3://`), so a caller can make this container
  fetch arbitrary URLs. Do not widen that: add no credentials, cloud env vars
  or extra volume mounts to this service without restricting `url` first.
- The container's only data mount is the COG folder. Keep it that way.

## Internationalization and Logging

- `raster-api` is not wired to `agri_i18n`. Its errors are TiTiler's, in
  English. If you add user-facing validation to a custom router, wire in
  `LocaleASGIMiddleware` the way vector-api does rather than hard-coding
  French.
- There is no custom logging. Use the root stdlib rule for anything you add.

## Testing

| Marker | File | What it exercises |
| --- | --- | --- |
| `unit` | `test_collections_endpoint.py`, `test_raster_app_routes.py` | directory scan on `tmp_path`; route surface of `raster_api.main.app` |
| `integration` | `test_collections_endpoint.py`, `test_raster_api_cog_integration.py` | the real TiTiler app via `TestClient` on a generated GeoTIFF |

- Nothing live is needed; "integration" here means real GDAL rendering in
  process.
- The `tmp_raster_valid_fixture` in `conftest.py` is a 10×10 uint8 EPSG:4326
  GeoTIFF. Pass it as `url=<path>.as_uri()`.
- Point `RASTER_COG_DIR` at `tmp_path` with `monkeypatch.setenv`; never scan
  the real `/data`.
- When adding a route, add it to the route-contract test so a base-image bump
  that drops it fails loudly.
