# Deployment Guide

Production deployment guide for MOS-GIS on a Linux server with Docker.

---

## Prerequisites

- Linux server (Ubuntu 22.04+ recommended)
- Docker + Docker Compose plugin
- A domain name pointed to your server's IP (optional for initial deploy — see [TLS section](#3-tls--caddy))
- Ports 80 and 443 open on the server firewall

### Server sizing

Stack consumption per scenario, from a measured load test (July 2026 — simulated map users issuing TiTiler tile, vector and STAC requests, with raster-api running 2 uvicorn workers):

| Scenario | Peak RAM | Peak vCPU | Latency (median / p95) |
| --- | --- | --- | --- |
| 1 user, no pipeline run | 1.6 GiB *(measured)* | ~1.7 *(measured)* | 0.19 s / 0.33 s |
| 5 users, no pipeline run | 2.1 GiB *(measured)* | ~3.7 *(measured)* | 0.74 s / 1.8 s |
| 1 user + pipeline run | ~5–6 GiB *(calculated)* | ~4 | — |
| 5 users + pipeline run | ~6–7 GiB *(calculated)* | ~5–6 (ceiling, not sustained) | tiles slower during the run |

Recommended server specs:

| Option | vCPU | RAM | SSD | What it enables |
| --- | --- | --- | --- | --- |
| Minimum | 2 | 4 GB | 60 GB | Demo / map browsing (~5 users), no data integrations on the server, chatbot via external LLM API |
| Full usage, external LLM | 4 | 8 GB | 100 GB | Concurrent users + data integrations (pipeline runs), chatbot via external LLM API |
| Full usage, in-container Ollama | 4 | 16 GB | 100 GB | Same, plus locally hosted chatbot LLM (Ollama — no API fees, data stays on the server) |

Notes:

- "With pipeline" figures add the pipeline's compose ceilings (2 GiB / 2 vCPU) and database insert activity (~2–3 GiB, 6 GiB ceiling) to the measured serving load.
- Running Ollama inside the chatbot backend adds ~4 GiB during inference — the main reason to pick 16 GB for production.
- Compose resource limits are ceilings, not reservations — idle usage of the whole stack is under 1 GiB.

---

## 1. Clone & configure

```bash
git clone https://github.com/Mon-Systeme-Fourrager/mos-gis.git
cd mos-gis
cp .env.example .env
```

---

## 2. Environment variables

Edit `.env` and set every value marked below. Leave others at their defaults unless you know you need to change them.

### Required

| Variable | What to do |
| --- | --- |
| `POSTGRES_PASS` | Admin (superuser) password — used for Docker init, healthcheck, and backups |
| `DB_PASS` | Application role password — used by all services to connect (`mos_gis` role) |
| `LLM_API_KEY` | Your OpenAI (or other provider) API key |
| `API_KEY` | Generate with `openssl rand -hex 32` — protects the chatbot endpoint |
| `ENABLE_AUTH` | Set to `true` to enforce the API key on the chatbot |
| `HOST_URL` | Your domain name (e.g. `mon-domaine.ca`) or server IP |
| `HOST_PROTOCOL` | `https` (once Caddy + TLS is configured) |
| `OPENEO_REFRESH_TOKEN` | OIDC refresh token for Copernicus Data Space — see the [OpenEO setup guide](../mos-pygeoapi/docs/OPENEO_SETUP.md) |

### Generate secrets

```bash
# Database admin password  (POSTGRES_PASS)
openssl rand -hex 24

# Application role password (DB_PASS)
openssl rand -hex 24

# Chatbot API key
openssl rand -hex 32
```

### Database credential model

Two PostgreSQL credentials exist to follow least-privilege:

| Variable | Role | Used by |
| --- | --- | --- |
| `POSTGRES_USER=postgres` | Superuser | Docker image init, `pg_dump` backups, healthcheck |
| `POSTGRES_PASS` | Superuser password | Same |
| `DB_USER=mos_gis` | App role (SELECT/INSERT/UPDATE/DELETE only) | All backend services |
| `DB_PASS` | App role password | Same |

The `mos_gis` role is created automatically by `scripts/create_app_role.sh` on first DB initialisation.

### CORS

`VECTOR_API_CORS_ORIGINS` is automatically derived from `HOST_PROTOCOL` and `HOST_URL` in `docker-compose.yml`. Changing the domain in `.env` updates CORS automatically — no extra step needed.

### Rate limiting

PyGeoAPI process routes are rate limited by Caddy. Defaults (per IP):

| Route | Limit |
| --- | --- |
| `POST /mos-pygeoapi/processes/*/execution` | 10 requests / minute |
| `GET /mos-pygeoapi/*` | 60 requests / minute |

Clients exceeding the limit receive `HTTP 429` with a `Retry-After` header. Adjust in `.env`:

```bash
RATE_LIMIT_PYGEOAPI_EXEC_EVENTS=10   # number of POST executions allowed
RATE_LIMIT_PYGEOAPI_EXEC_WINDOW=1m   # per window duration
RATE_LIMIT_PYGEOAPI_BROWSE_EVENTS=60
RATE_LIMIT_PYGEOAPI_BROWSE_WINDOW=1m
```

After changing these values: `docker compose up -d caddy` (no rebuild needed — values are env vars).

---

## 3. TLS / Caddy

Caddy is the single entry point for all traffic (ports 80 and 443). Backend services are not exposed directly.

### Local / staging (self-signed certificate)

The default `Caddyfile` uses `tls internal` with `localhost, mos-gis.local`. No changes needed — Caddy issues a self-signed cert automatically.

To add `mos-gis.local` to your local hosts file (Windows/Mac client):
```
<server-ip>  mos-gis.local
```

### Production (real domain + Let's Encrypt)

Once your DNS is pointed at the server:

1. Edit `Caddyfile` — replace the host block:
   ```caddyfile
   # Before
   localhost, mos-gis.local {
       tls internal
       reverse_proxy home:8080
   }

   # After
   mon-domaine.ca {
       reverse_proxy home:8080
   }
   ```
2. Update `.env`:
   ```
   HOST_PROTOCOL=https
   HOST_URL=mon-domaine.ca
   ```
3. Restart Caddy:
   ```bash
   docker compose restart caddy
   ```

Caddy fetches and renews the Let's Encrypt certificate automatically. The `caddy_data` Docker volume persists the certificate across restarts — do not delete it.

---

## 4. Build & start

```bash
# First deploy
docker compose up -d --build

# Check all services are healthy
docker compose ps
```

Expected healthy services: `caddy`, `home`, `database`, `stac-api`, `raster-api`, `vector-api`, `mos-pygeoapi`, `mos-chatbot-backend`, `mos-chatbot-frontend`, `stac-browser`, `gis-pipeline`.

---

## 5. Production images (no test dependencies)

`docker-compose.yml` targets the `test` stage for each service so CI tests can run. For a clean production build without test tooling:

```bash
docker build --target runtime -f stac-api/Dockerfile.stac-api .
docker build --target runtime -f vector-api/Dockerfile.vector-api .
docker build --target runtime -f raster-api/Dockerfile.raster-api .
docker build --target runtime -f mos-pygeoapi/Dockerfile.mos-pygeoapi .
docker build --target runtime -f gis-pipeline/Dockerfile.gis-pipeline .
```

---

## 6. Security checklist

- [ ] `POSTGRES_PASS` set to a strong random value (never leave blank)
- [ ] `DB_PASS` set to a different strong random value (never leave blank)
- [ ] `API_KEY` generated with `openssl rand -hex 32`
- [ ] `ENABLE_AUTH=true` in `.env`
- [ ] `LLM_API_KEY` set (never commit this to git)
- [ ] `.env` not committed to git (it is in `.gitignore`)
- [ ] Ports 8081–8085, 5000, 8005, 3001 **not** open on the server firewall — only 80 and 443
- [ ] Database port `5439` bound to `127.0.0.1` only (already the case in `docker-compose.yml`)

---

## 7. Ongoing maintenance

### OpenEO refresh token

The Copernicus Data Space token (`OPENEO_REFRESH_TOKEN`) expires every ~30 days. Regeneration steps, token storage, and reload instructions are in the [OpenEO setup guide](../mos-pygeoapi/docs/OPENEO_SETUP.md).

### TLS certificate

Caddy renews Let's Encrypt certificates automatically. No action needed unless the `caddy_data` volume is deleted.

### Updates

```bash
git pull
docker compose up -d --build
```

### Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f mos-chatbot-backend
docker compose logs -f caddy
```

### Backup

```bash
# PostgreSQL dump (run as admin superuser so all schemas are captured)
docker compose exec database pg_dump -U postgres mos_gis > backup_$(date +%Y%m%d).sql

# DuckDB (file copy is safe when pipeline is not writing)
cp data/duckdb/eoapi.duckdb backup_duckdb_$(date +%Y%m%d).duckdb
```

### Changing the application role password

The `mos_gis` role password is set once at first DB init. To rotate it after initial deployment:

```bash
# 1. Update DB_PASS in .env
# 2. Apply the new password to the running database
docker compose exec database psql -U postgres -d mos_gis \
  -c "ALTER ROLE mos_gis WITH PASSWORD 'your-new-password';"
# 3. Restart services so they pick up the new DB_PASS
docker compose up -d
```

---

## Domain migration summary

All changes needed when moving from self-signed to a real domain:

| File | Change |
| --- | --- |
| `Caddyfile` | Replace `localhost, mos-gis.local {` + `tls internal` with `ton-domaine.ca {` |
| `.env` | `HOST_URL=ton-domaine.ca`, `HOST_PROTOCOL=https` |

---

## 8. Restoring a production database dump

Use this procedure when seeding a fresh database from a `pg_dump` backup of a previous deployment. Place your compressed dump in `data/demo/` (create the directory if needed) — the restore command below mounts it into the container.

For a continuous connection to an existing PostgreSQL database (logical replication, foreign data wrapper) instead of one-off dumps, see [Database integration](data/database_integration.md).

### Why a filtered restore

A full plain-SQL dump contains both the `pgstac` schema DDL and the `public` schema data. The pgstac version in the dump may differ from the one initialised by the current Docker image. Restoring mismatched pgstac DDL corrupts the schema and causes `invalid command \N` loops in psql as data rows get interpreted as commands.

The solution is `scripts/filter_public_copy.py`: it reads the dump from stdin and writes only the `COPY public.*` data blocks to stdout, skipping every `COPY pgstac.*` block. The pgstac schema is left exactly as Docker initialised it.

### Step 1 — restore only the public schema

```bash
# Stream the compressed dump through the filter and straight into psql.
# Uses the pgstac image because it ships both python3 and psql —
# use the same image tag as the database service in docker-compose.yml.
docker run --rm -i \
  --network eoapi-network \
  -v "$(pwd)/scripts/filter_public_copy.py:/filter.py:ro" \
  -v "$(pwd)/data/demo:/dump:ro" \
  ghcr.io/stac-utils/pgstac:<same-tag-as-docker-compose> \
  bash -c "
    gunzip -c /dump/pgstac_prod_<DATE>.sql.gz \
      | python3 /filter.py \
      | psql -h database -U postgres -d mos_gis
  "
```

Replace `<DATE>` with the actual filename suffix (e.g. `20260615`). Each `COPY <n>` line in the output confirms a table block was loaded. The command exits 0 on success.

### Step 2 — repair the pgstac schema

A dump created from an older pgstac version includes DDL that overwrites the pgstac schema the Docker image set up, typically leaving `pgstac.collections` and `pgstac.collections_asitems` missing. Without these objects the stac-api returns `HTTP 500` on every `/collections` request. Partial overlaps between the dump's schema and the current one also cause `pgstac_settings` to accumulate duplicate rows, which produces `CardinalityViolationError` on startup.

Run this block to create any missing objects and remove duplicates — it is safe to run even when nothing is broken:

```bash
docker compose exec database psql -U postgres -d mos_gis -c "
SET search_path TO pgstac, public;

-- Create collections table if missing (added in pgstac 0.7+)
CREATE TABLE IF NOT EXISTS collections (
    key bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id text GENERATED ALWAYS AS (content->>'id') STORED UNIQUE NOT NULL,
    content JSONB NOT NULL,
    base_item jsonb GENERATED ALWAYS AS (pgstac.collection_base_item(content)) STORED,
    geometry geometry GENERATED ALWAYS AS (pgstac.collection_geom(content)) STORED,
    datetime timestamptz GENERATED ALWAYS AS (pgstac.collection_datetime(content)) STORED,
    end_datetime timestamptz GENERATED ALWAYS AS (pgstac.collection_enddatetime(content)) STORED,
    private jsonb,
    partition_trunc text CHECK (partition_trunc IN ('year', 'month'))
);

-- Create collections_asitems view if missing
CREATE OR REPLACE VIEW collections_asitems AS
SELECT
    id, geometry, 'collections' AS collection, datetime, end_datetime,
    jsonb_build_object(
        'properties', content - '{links,assets,stac_version,stac_extensions}',
        'links', content->'links',
        'assets', content->'assets',
        'stac_version', content->'stac_version',
        'stac_extensions', content->'stac_extensions'
    ) AS content,
    content AS collectionjson
FROM collections;

-- Remove duplicate settings rows (accumulate when dump DDL overlaps current schema)
DELETE FROM pgstac_settings a
USING pgstac_settings b
WHERE a.ctid < b.ctid AND a.name = b.name;

-- Remove duplicate migration version rows
DELETE FROM migrations a
USING migrations b
WHERE a.ctid < b.ctid AND a.version = b.version;

-- Record the current schema version if not already present
-- (replace <PGSTAC_VERSION> with the version of your pgstac Docker image)
INSERT INTO migrations (version) SELECT '<PGSTAC_VERSION>' WHERE NOT EXISTS (
    SELECT 1 FROM migrations WHERE version = '<PGSTAC_VERSION>'
);
"
```

Then restart the stac-api to pick up the repaired schema:

```bash
docker compose restart stac-api
```

### Step 3 — transfer table ownership to the app role

Tables restored from a dump are owned by `postgres`. The `mos_gis` app role needs ownership to `DROP` and `ALTER` them during pipeline ingestion:

```bash
docker compose exec database psql -U postgres -d mos_gis -c "
DO \$\$
DECLARE r RECORD;
BEGIN
    FOR r IN
        SELECT tablename FROM pg_tables
        WHERE schemaname = 'public' AND tableowner = 'postgres'
    LOOP
        EXECUTE format('ALTER TABLE public.%I OWNER TO mos_gis', r.tablename);
    END LOOP;
END \$\$;
"
```

### Step 4 — ensure the app role can create tables

PostgreSQL 15 does not grant `CREATE` on the `public` schema by default. `scripts/create_app_role.sh` now includes this grant, so a fresh database init is self-contained. On a database that was initialised before this change, apply it manually once:

```bash
docker compose exec database psql -U postgres -d mos_gis \
  -c "GRANT CREATE ON SCHEMA public TO mos_gis;"
```

### Step 5 — create GIST spatial indexes

A `pg_dump` does not always preserve spatial indexes. Without GIST indexes on geometry columns, TiPg (vector-api) performs sequential scans and returns empty tile responses. Create indexes on all public geometry tables in one pass:

```bash
docker compose exec database psql -U postgres -d mos_gis -t -A -c "
SELECT format(
    'CREATE INDEX IF NOT EXISTS %I ON public.%I USING GIST (%I);',
    f_table_name || '_' || f_geometry_column || '_gist',
    f_table_name,
    f_geometry_column
)
FROM geometry_columns
WHERE f_table_schema = 'public';
" | docker compose exec -T database psql -U postgres -d mos_gis
```

This generates and immediately executes one `CREATE INDEX IF NOT EXISTS` per geometry column. Empty tables are indexed without error. On a database with ~240 geometry tables the pass takes a few minutes.

### Step 6 — rebuild the GRHQ water union table

`scripts/build_grhq_water_union.py` merges all eligible GRHQ hydrological line and polygon tables into a single `public.grhq_water_union` table. This union is the data source for "distance from water" spatial queries in the SOM Calculator. Run it after loading GRHQ data from the dump (step 1).

```bash
docker compose run --rm \
  -v "$(pwd)/scripts/build_grhq_water_union.py:/tmp/build_grhq_water_union.py:ro" \
  gis-pipeline \
  python3 /tmp/build_grhq_water_union.py
```

The script inserts rows in batches of 5 000 with independent commits to avoid OOM. When it finishes, it prints the three manual steps to atomically swap the new table into place and create the spatial index:

```sql
DROP TABLE IF EXISTS public.grhq_water_union;
ALTER TABLE public.grhq_water_union_new RENAME TO grhq_water_union;
CREATE INDEX CONCURRENTLY grhq_water_union_geom_idx
    ON public.grhq_water_union USING GIST(geometry);
```

Run those three statements as the `mos_gis` user (or `postgres` if the table owner needs to change):

```bash
docker compose exec database psql -U mos_gis -d mos_gis -c "
  DROP TABLE IF EXISTS public.grhq_water_union;
  ALTER TABLE public.grhq_water_union_new RENAME TO grhq_water_union;
"
docker compose exec database psql -U mos_gis -d mos_gis -c "
  CREATE INDEX CONCURRENTLY grhq_water_union_geom_idx
      ON public.grhq_water_union USING GIST(geometry);
"
```

`CREATE INDEX CONCURRENTLY` must run outside a transaction block, so it is issued as a separate command.

### Step 7 — run the gis-pipeline

Ingest all input files from `/data/input`:

```bash
docker compose run --rm gis-pipeline python3 -m gis_pipeline.main \
  --input /data/input \
  --crs 4326 \
  --collection mos_gis_collection
```

The final log lines report `Processed`, `Errors`, and `Non_spatial_csv` counts. `Errors: 0` is the target. After a successful run, vector layers, COGs, and STAC items are all up to date. The pipeline automatically stamps `has_gee_data` on `som_field_boundaries` at the end of every run — no manual post-step needed.

---

## First-time deploy on a server with existing data

If you are migrating from a previous install that used `POSTGRES_DBNAME=postgres` and `POSTGRES_USER=postgres`:

```bash
# 1. Dump the old database from the running container
docker compose exec database pg_dump -U postgres postgres > migration_backup.sql

# 2. Stop services and wipe the data volume (this destroys existing data)
docker compose down
rm -rf data/pg/.pgdata

# 3. Update .env with new credentials (POSTGRES_DBNAME=mos_gis, DB_USER, DB_PASS, etc.)

# 4. Start fresh — Docker creates the mos_gis database and runs init scripts
docker compose up -d database
docker compose exec database psql -U postgres -d mos_gis < migration_backup.sql

# 5. Start remaining services
docker compose up -d
```

Then: `docker compose restart caddy`. CORS and all internal service URLs update automatically.
