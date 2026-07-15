# stac-api

STAC 1.0.0 catalog API backed by pgSTAC. Search raster and vector datasets by spatial extent, time range, and metadata properties.

**Port**: 8081 | **Requires**: PostGIS with pgSTAC schema

Interactive API docs: `http://<host>/mos-stac/api.html`

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

```bash
# Spatial filter
curl "http://<host>:8081/search?bbox=-73,45,-71,46"

# Collection + CQL filter
curl -X POST http://<host>:8081/search \
  -H "Content-Type: application/json" \
  -d '{"collections":["sentinel2_eo_products"],"bbox":[-73,45,-71,46],"filter":{"op":"<","args":[{"property":"cloud_cover"},20]}}'
```

## Configuration

| Variable | Description |
| --- | --- |
| `STAC_API_URL` | Public base URL used for self-links in responses |
| `POSTGRES_HOST` / `POSTGRES_PORT` | pgSTAC database connection |
| `POSTGRES_USER` / `POSTGRES_PASS` / `POSTGRES_DBNAME` | Database credentials |

## Requirements

- PostGIS database with the pgSTAC schema initialized
- STAC items and collections are published by `gis-pipeline` after each pipeline run
