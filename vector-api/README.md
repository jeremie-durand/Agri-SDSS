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
- **Pagination** — `limit` + `offset` on all item endpoints. A Parquet page can hold fewer than `limit` features when their geometries together exceed `VECTOR_API_MAX_PAGE_VERTICES`; follow its `next` link rather than adding `limit` to `offset`. A single feature above that budget answers 413
- **Split features** — in layers of at most 50 000 rows, gis-pipeline stores a polygon of more than 100 000 vertices as several pieces that share `split_source_gid` and are numbered by `split_part`. Group by `split_source_gid` to rebuild the source feature, and do not sum its attributes (such as an area) over the pieces
- **Binary columns** — Parquet `BLOB` columns, and geometry columns other than the feature geometry, are left out of feature properties and queryables
- **Localised errors** — French by default; send `Accept-Language: en` or `?lang=en` for English
- **Warm start** — right after start-up, the Parquet collection metadata (columns, feature count, extent) is computed in the background, so the first `/parquet/collections` does not pay for it
- **Offline start** — the image ships DuckDB's `spatial` extension, so a new container needs no network access to load it

## Checking the `.duckdb` indexes

A GeoParquet collection is fast only when its RTree-indexed `<id>.duckdb` file
exists next to it; otherwise it is served from the raw Parquet file, much more
slowly, and vector-api logs one warning per collection above
`VECTOR_API_RAW_PARQUET_WARN_MB`. To list those collections on demand, for
example after a pipeline run or a deploy:

```bash
make check-materialized
```

It prints one line per geometry collection above the threshold whose `.duckdb`
is `missing` or `unreadable` (or a Parquet file it could not read, as
`unchecked`), then a summary, and exits 1 if it listed any (2 if
the setting or the data directory is invalid). It runs in a one-off container,
so the running vector-api is not recreated.

## Checking peak memory

The heaviest requests (one 54 MiB polygon, a page shortened to the vertex
budget) must stay clear of the container's 1 GiB limit. To measure them on the
real data, after a deploy or a change to the memory settings, once
`docker compose logs vector-api` shows the
`Parquet schema warm-up: N of M collections scanned` line (the warm-up's own
scans would otherwise land inside the measurements):

```bash
make check-parquet-memory
```

It runs inside the running vector-api, sends each known heavy request one at a
time, and prints its status, body size, peak RSS, swap and time. It exits 1 if
a peak passes `VECTOR_API_PEAK_RSS_MAX_MB` (default 950; set it on the `make`
command line to override), a request fails, or the process swapped, and 2 if
it cannot measure (for example when PID 1 is not the uvicorn server). A
collection missing from the stack, on `/parquet` or `/postgis`, is skipped. If
the container restarts during the run, the command ends without its summary
line: count that as a failure, it is the out-of-memory kill the probe exists
to catch.

One failure is known and accepted until the page budget is lowered (#292
follow-up): `grhq_hr_04ac_s_udh/items?limit=10000`, a page shortened to the
1.5M-vertex budget, peaks at 774-960 MB depending on what DuckDB has cached,
so it can fail at 950 MB. A FAIL on any other request is real.

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
| `DUCKDB_MEMORY_LIMIT` | `819MB` | DuckDB `memory_limit` for each DuckDB instance (the in-memory one and each open `.duckdb`) |
| `VECTOR_API_MAX_OPEN_DUCKDB` | `2` | Maximum number of materialized `.duckdb` collections kept open at once |
| `VECTOR_API_MAX_DUCKDB_QUERIES` | `1` | Maximum number of concurrent queries on materialized collections |
| `VECTOR_API_MAX_PAGE_VERTICES` | `1500000` | Most geometry vertices one Parquet items page or item may hold, about 56 MiB of GeoJSON. The default sits just above the largest real feature; raise it only together with the container memory |
| `VECTOR_API_RAW_PARQUET_WARN_MB` | `50` | Parquet size in MB above which a geometry collection served without its `.duckdb` file is logged as a warning |
| `VECTOR_API_CORS_ORIGINS` | _(empty)_ | Comma-separated allowed CORS origins |
| `TIPG_DB_FUNCTIONS` | `[]` (set in `docker-compose.yml`) | SQL functions TiPg publishes as `/postgis` collections. `[]` publishes none, which keeps PostGIS's own functions (`postgis_srs`, `st_squaregrid`, …) out of the catalog. To publish a project function, list it by `schema.name`, e.g. `["public.my_function"]` |

## PostGIS table requirements

- Geometry column with a valid SRID (EPSG:4326 recommended)
- Primary key column for feature identification
- Spatial index (`GIST`) for bbox query performance
