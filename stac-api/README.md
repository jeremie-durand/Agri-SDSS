# stac-api

STAC catalog API (stac-fastapi + pgSTAC); items and collections follow STAC 1.1.0. Search raster and vector datasets by spatial extent, time range, and metadata properties.

**Port**: 8081 | **Requires**: PostGIS with pgSTAC schema

Interactive API docs: `http://<host>/stac-api/api.html`

## Start

```bash
docker compose up -d stac-api
```

## Key endpoints

| Endpoint | Description |
| --- | --- |
| `GET /collections` | List all collections |
| `GET /collections/{id}` | Collection metadata |
| `GET /collections/{id}/items` | Items in a collection |
| `GET /collections/{id}/items/{itemId}` | Single item |
| `POST /search` | Spatial + temporal + CQL filter search |
| `GET /search` | Same as POST but with query parameters |

## Key behaviours

- **Spatial search** — `bbox` and GeoJSON geometry filters
- **Temporal search** — `datetime` parameter with open/closed intervals (e.g. `2023-01-01/2023-12-31`)
- **CQL2 filtering** — property filters such as `cloud_cover < 20` on `POST /search`
- **STAC extensions** — EO, SAR, Projection, and Raster extensions supported on items
- **OGC API Features** — `/collections/{id}/items` follows OGC API Features Part 1

## Quick search

The STAC API is reached through the single public origin at `https://<host>/stac-api/`.
Against a local deployment add `-k` (`curl -k https://localhost/...`) — the certificate is
self-signed.

```bash
# Spatial filter
curl "https://<host>/stac-api/search?bbox=-73,45,-71,46"

# Collection + CQL filter
curl -X POST https://<host>/stac-api/search \
  -H "Content-Type: application/json" \
  -d '{"collections":["sentinel2_eo_products"],"bbox":[-73,45,-71,46],"filter":{"op":"<","args":[{"property":"cloud_cover"},20]}}'
```

## Configuration

| Variable | Description |
| --- | --- |
| `PGHOST` / `PGPORT` / `PGDATABASE` | pgSTAC database connection |
| `PGUSER` / `PGPASSWORD` | App role the API runs as (`DB_USER` / `DB_PASS`) |
| `PGSTAC_ADMIN_USER` / `PGSTAC_ADMIN_PASS` | Superuser, used only by the entrypoint to grant pgstac access to the app role (and by test cleanup) |
| `APP_ROOT_PATH` | Public path prefix (`/stac-api`), passed to uvicorn `--root-path`; self-links are built from it |
| `CORS_ORIGINS` | Allowed CORS origins (`*` by default in `.env`) |
| `ENABLE_TRANSACTIONS_EXTENSIONS` | Enables the write endpoints used by gis-pipeline and process-api |

`STAC_API_URL` is not read by stac-api itself: it is the internal URL other
services use to reach it (`http://stac-api:8081`).

## Requirements

- PostGIS database with the pgSTAC schema initialized
- STAC items and collections are published by `gis-pipeline` after each pipeline run
