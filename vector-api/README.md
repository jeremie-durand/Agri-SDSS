# vector-api

OGC API – Features service with two backends: **PostGIS** (via TiPg) and **DuckDB/GeoParquet** (auto-discovered).

**Port**: 8083 | **Requires**: PostGIS; DuckDB Parquet files in `data/duckdb/`

Interactive API docs: `http://<host>/vector-api/postgis/api.html` (PostGIS) · `http://<host>/vector-api/parquet/api.html` (Parquet)

## Start

```bash
docker compose up -d vector-api
```

## Key endpoints

| Endpoint | Description |
| --- | --- |
| `GET /postgis/collections` | List all PostGIS collections |
| `GET /postgis/collections/{id}/items` | Features with spatial + attribute filtering |
| `GET /postgis/collections/{id}/queryables` | Filterable properties for a collection |
| `GET /parquet/collections` | List all GeoParquet collections |
| `GET /parquet/collections/{id}/items` | Parquet features with spatial filtering |

## Backends

| Prefix | Source | Notes |
| --- | --- | --- |
| `/postgis/` | PostgreSQL/PostGIS | All tables with a geometry column in the `public` schema are exposed automatically |
| `/parquet/` | DuckDB GeoParquet | `.parquet` files in `DUCKDB_DATA_DIR` are exposed automatically — no restart needed |

## Key behaviours

- **Auto-discovery** — add a PostGIS table or drop a `.parquet` file and it appears immediately
- **Spatial filtering** — all collections support `bbox` query parameter
- **CQL filtering** — attribute and spatial filters on PostGIS collections (`/postgis/` only)
- **Output formats** — GeoJSON (default), CSV (`?f=csv`), GeoJSON-seq (`?f=geojsonseq`)
- **Pagination** — `limit` + `offset` on all item endpoints

## Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `DUCKDB_DATA_DIR` | `/data/duckdb` | Directory scanned for `.parquet` files |
| `VECTOR_API_CORS_ORIGINS` | _(empty)_ | Comma-separated allowed CORS origins |

## PostGIS table requirements

- Geometry column with a valid SRID (EPSG:4326 recommended)
- Primary key column for feature identification
- Spatial index (`GIST`) for bbox query performance
