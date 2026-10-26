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
| `POST /pedo-properties` | IRDA soil components of a parcel, with NRCS hydrologic group and bulk density by depth |

### `POST /pedo-properties`

Body: `{"geometry": <GeoJSON geometry>}`. Joins the IRDA pedological coverage (2026_01)
for the parcel: the polygons it overlaps (PostGIS), their soil components
(`couverture_pps`), each component's hydrologic group (BDHP 2026) and its bulk density
by horizon (`ppc_eessaq`, falling back to the 1990 inventory without depths).

```json
{
  "components": [
    {
      "composante": "21Cw", "code_sol": "CWA", "share_pct": 55.0,
      "hydrologic_group": "C",
      "bulk_density": {
        "source": "eessaq",
        "horizons": [
          {"horizon": "Ap1", "depth_top_cm": 0.0, "depth_bottom_cm": 15.0, "g_cm3": 1.167}
        ]
      }
    }
  ],
  "dominant_hydrologic_group": "C",
  "described_pct": 75.0
}
```

- `share_pct` is the share of the parcel attributed to a component (overlap × component
  percentage); `described_pct` is their sum — the rest of the parcel has no component data.
- `hydrologic_group` is `A`–`D` or a dual group such as `C/D`; `null` when unknown.
- `bulk_density.source` is `eessaq` (depths known), `inventaire_1990` (no depths) or `null`.
- Table names are configurable: `PEDO_POLYGON_TABLE_NAME`, `PEDO_COMPONENTS_COLLECTION`,
  `PEDO_HYDRO_COLLECTION`, `PEDO_BULK_DENSITY_COLLECTION`, `PEDO_BULK_DENSITY_1990_COLLECTION`.

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
- **Localised errors** — French by default; send `Accept-Language: en` or `?lang=en` for English

## Language

Error messages are returned in **French by default**:

```bash
curl -H "Accept-Language: en" -H "Content-Type: application/json" -d '{}' \
  .../vector-api/pedo-properties
```

Status codes and response structure are identical in both languages — only the `detail` text
changes. See [Internationalization](../docs/I18N.md).

## Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `DUCKDB_DATA_DIR` | `/data/duckdb` | Directory scanned for `.parquet` files |
| `VECTOR_API_CORS_ORIGINS` | _(empty)_ | Comma-separated allowed CORS origins |

## PostGIS table requirements

- Geometry column with a valid SRID (EPSG:4326 recommended)
- Primary key column for feature identification
- Spatial index (`GIST`) for bbox query performance
