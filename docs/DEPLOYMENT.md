# Deployment Guide

Production deployment guide for Agri-SDSS on a Linux server with Docker.

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

### Reference deployment

The performance figures published for this platform were measured on this host;
the table gives its configuration at the time of the v2.0.0 release.
Service and library versions are pinned in each service's `Dockerfile.<service>`
and `requirements-<service>.txt`; the host-side versions are not, so they are
recorded here:

| Item | Value |
| --- | --- |
| Host | OVHcloud virtual private server, Ubuntu 26.04 |
| CPU / RAM / storage | 6 vCPU, 11 GiB RAM, two 100 GB virtual disks |
| Docker Engine | 29.8.1 |
| Docker Compose | 5.5.1 |

---

## 1. Clone & configure

```bash
git clone https://github.com/jeremie-durand/Agri-SDSS.git
cd Agri-SDSS
cp .env.example .env
```

---

## 2. Environment variables

Edit `.env` and set every value marked below. Leave others at their defaults unless you know you need to change them.

### Required

| Variable | What to do |
| --- | --- |
| `POSTGRES_PASS` | Admin (superuser) password — used for Docker init, healthcheck, and backups |
| `DB_PASS` | Application role password — used by all services to connect (`agri_sdss` role) |
| `LLM_API_KEY` | Your OpenAI (or other provider) API key |
| `API_KEY` | Generate with `openssl rand -hex 32` — protects the chatbot endpoint |
| `ENABLE_AUTH` | Set to `true` to enforce the API key on the chatbot |
| `HOST_URL` | Your domain name (e.g. `mon-domaine.ca`) or server IP |
| `HOST_PROTOCOL` | `https` (once Caddy + TLS is configured) |
| `OPENEO_REFRESH_TOKEN` | OIDC refresh token for Copernicus Data Space — see the [OpenEO setup guide](../process-api/docs/OPENEO_SETUP.md) |

> **Gate: `HOST_URL` must be the real public domain before you publish anything.**
> process-api and gis-pipeline both build STAC asset hrefs from
> `HOST_PROTOCOL://HOST_URL` — the URL a client will later fetch the COG from. The
> repo's own `.env.example` ships `HOST_PROTOCOL=https` with `HOST_URL=localhost`,
> which is fine for a local demo but produces `https://localhost/cog/x.tif` if it
> is still set that way when `lidar-fetch`, `sentinel-fetch`, or the gis-pipeline
> COG step runs. That URL is syntactically valid and resolves for nobody, and it
> gets written permanently into the public STAC catalog — arguably worse than a
> container-local path, which at least looks obviously broken to a client.
>
> **Before running any STAC-publishing process:** set `HOST_URL` to the domain
> or IP the deployment is actually reachable at, and confirm with
> `echo "$HOST_PROTOCOL://$HOST_URL"` (or check the running containers'
> environment) rather than trusting `.env` was edited. Items already published
> with a wrong value are not fixed by changing `.env` after the fact — they need
> the [republication sweep](#republishing-stac-items-after-an-href-change) below.

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
| `POSTGRES_USER=postgres` | Superuser | Docker image init, backups, healthcheck, stac-api grant step, pgSTAC tools (sections 8 and 9) |
| `POSTGRES_PASS` | Superuser password | Same |
| `DB_USER=agri_sdss` | App role: DML and `CREATE` on `public`; pgSTAC through `pgstac_ingest`, without `CREATE` on `pgstac` | All backend services |
| `DB_PASS` | App role password | Same |

The `agri_sdss` role is created automatically by `scripts/create_app_role.sh` on first DB initialisation. stac-api re-applies its pgSTAC access at every start (`stac-api/scripts/apply_pgstac_grants.sql`), which also clears the direct `pgstac` grants a restored dump brings back.

### Process jobs table

process-api creates the jobs table at every start
(`python -m processes.jobs.schema`, idempotent) with the app role, and every
worker does the same. The table is `PROCESS_JOBS_TABLE` (default
`public.process_jobs`); `server.manager.connection.table` in
`pygeoapi-config.yaml` overrides it when set. At every start, not only the
first, the app role needs `CREATE` on the table's schema and must own the
table; owning the schema and letting process-api create the table gives
both. Owning the schema alone does not make the role owner of a table that
another role created there (a superuser, or a `pg_restore` keeping the
original owner). PostgreSQL checks these before it sees
that the table or its indexes already exist, so a role that owns the table
but has only `USAGE` on the schema stops process-api at boot. Here the app
role already has `CREATE` on `public` and owns the table it created. The name
must be lowercase `schema.name` or `name`, at most 56 characters. The table holds the OGC API – Processes job records and the async
queue. It has no geometry, so vector-api does not list it.

process-api and its workers must connect to PostgreSQL directly. Workers wait
for new jobs with `LISTEN`, a running job holds a session advisory lock, and a
crash is detected when that session ends. A connection pooler in transaction
mode would break this. The job timeout,
retention and worker polling are set by the `PROCESS_*` variables in
`.env.example`.

### Process worker

`process-worker` runs the async jobs (`Prefer: respond-async` on
`sentinel-fetch`, `lidar-fetch` and `som-predict-soil`). It uses the process-api
image with `python -m processes.worker`, mounts the same `./data` volumes, and
has no port. Each replica runs one job at a time, each job in its own child
process:

```bash
docker compose up -d --scale process-worker=2   # two jobs at a time
docker compose logs -f process-worker           # "ready", "Claimed job", "Finished job"
```

- **Memory.** Each replica is capped at 2 GB and 1 vCPU, like process-api. Add
  2 GB of headroom per replica to the sizing above. A job killed by the memory
  limit is marked `failed`; the worker itself keeps running.
- **No worker running.** Async jobs stay `accepted` forever, and the home map
  gives up after 35 minutes. Check `docker compose ps process-worker`.
- **Crash.** A job whose worker died is marked `failed` by the next sweep of
  any worker (`PROCESS_WORKER_SWEEP_SECONDS`). Failed jobs are not retried.
- **One host.** Replicas must share the host of the `./data` mounts: the SOM
  training lock is an `flock` on `/data/duckdb`.

### CORS

`VECTOR_API_CORS_ORIGINS` is automatically derived from `HOST_PROTOCOL` and `HOST_URL` in `docker-compose.yml`. Changing the domain in `.env` updates CORS automatically — no extra step needed.

### Rate limiting

Caddy rate-limits per client IP. Defaults:

| Route | Limit |
| --- | --- |
| `POST /process-api/processes/*/execution` | 10 requests / minute |
| `GET /process-api/*` | 60 requests / minute |
| `POST` chatbot LLM routes (`/api/query`, `/api/geoint/*`, `/sdss/*`, …) | 10 requests / minute |
| `POST` chatbot catalogue searches (`/api/stac-search`, …) | 30 requests / minute |
| `GET /api/*` | 60 requests / minute |
| `GET /cog/*` | 30 requests / minute |

Clients exceeding a limit receive `HTTP 429` with a `Retry-After` header.

The limits are set in `caddy/Caddyfile` itself — no `.env` variable changes them. To
adjust one, edit the zone's `window` / `events`, then:

```bash
docker compose restart caddy   # Caddyfile is bind-mounted, no rebuild needed
```

Zone details: [caddy/CLAUDE.md](../caddy/CLAUDE.md#rate-limit-zones).

---

## 3. TLS / Caddy

Caddy is the single entry point for all traffic (ports 80 and 443). Backend services are not exposed directly.

### Local / staging (self-signed certificate)

With `SITE_ADDRESS` and `ACME_EMAIL` unset in `.env`, Caddy serves
`localhost, agri-sdss.local` with `tls internal`. No changes needed — Caddy issues a
self-signed cert automatically.

To add `agri-sdss.local` to your local hosts file (Windows/Mac client):

```text
<server-ip>  agri-sdss.local
```

### Production (real domain + Let's Encrypt)

Once your DNS is pointed at the server, no file needs editing — the `Caddyfile` reads
its site address and TLS mode from `.env`:

1. Update `.env`:

   ```ini
   SITE_ADDRESS=mon-domaine.ca        # Caddy site address (default: localhost, agri-sdss.local)
   ACME_EMAIL=admin@mon-domaine.ca    # Let's Encrypt account; unset = tls internal (self-signed)
   HOST_PROTOCOL=https
   HOST_URL=mon-domaine.ca
   ```

2. Recreate the services so they pick up the new values (a plain `restart` keeps the
   old environment):

   ```bash
   docker compose up -d
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

Expected healthy services: `caddy`, `home`, `database`, `stac-api`, `raster-api`, `vector-api`, `process-api`, `chatbot-backend`, `chatbot-frontend`, `stac-browser`, `gis-pipeline`.

---

## 5. Production images (no test dependencies)

`docker-compose.yml` targets the `test` stage for each service so CI tests can run. For a clean production build without test tooling:

```bash
docker build --target runtime -f stac-api/Dockerfile.stac-api .
docker build --target runtime -f vector-api/Dockerfile.vector-api .
docker build --target runtime -f raster-api/Dockerfile.raster-api .
docker build --target runtime -f process-api/Dockerfile.process-api .
docker build --target runtime -f gis-pipeline/Dockerfile.gis-pipeline .
```

---

## 6. Security checklist

- [ ] `HOST_URL` set to the real public domain/IP, not the `localhost` default — see the [gate above](#2-environment-variables) before running any STAC-publishing process
- [ ] `POSTGRES_PASS` set to a strong random value (never leave blank)
- [ ] `DB_PASS` set to a different strong random value (never leave blank)
- [ ] `API_KEY` generated with `openssl rand -hex 32`
- [ ] `ENABLE_AUTH=true` in `.env`
- [ ] `LLM_API_KEY` set (never commit this to git)
- [ ] `.env` not committed to git (it is in `.gitignore`)
- [ ] Ports 8081–8085, 5000, 8005, 3001 **not** open on the server firewall — only 80 and 443
- [ ] Database port `5439` bound to `127.0.0.1` only (already the case in `docker-compose.yml`)
- [ ] `https://<host>/process-api/jobs` answers `404` and `DELETE https://<host>/process-api/jobs/<id>` answers `405`. home nginx enforces both: a job id is the only key to a job's inputs and results, so jobs are never listed or dismissed publicly.
- [ ] `https://<host>/vector-api/postgis/collections/public.som_soil_samples/items` and `https://<host>/vector-api/parquet/collections/som_soil_samples` answer `404`, and likewise for `som_soil_analysis` and `som_field_boundaries`. `TIPG_DB_EXCLUDE_TABLES` (default in `docker-compose.yml`) hides these private tables from both vector-api backends; a value set in `.env` must still list them. See the [vector-api configuration](../vector-api/README.md#configuration).
- [ ] Every SOM model bundle in `$DUCKDB_DATA_DIR/som_models/` was trained by this deployment, or copied from a trusted source with its SHA-256 checked: a bundle is a pickle, and loading it runs any code it contains. See [How predictions are produced](../process-api/docs/SOM_PREDICT_SOIL_SPECS.md#how-predictions-are-produced).

---

## 7. Ongoing maintenance

### OpenEO refresh token

The Copernicus Data Space token (`OPENEO_REFRESH_TOKEN`) expires every ~30 days. Regeneration steps, token storage, and reload instructions are in the [OpenEO setup guide](../process-api/docs/OPENEO_SETUP.md).

### TLS certificate

Caddy renews Let's Encrypt certificates automatically. No action needed unless the `caddy_data` volume is deleted.

### Updates

```bash
git pull
docker compose up -d --build
```

**The release that moves the database to PostgreSQL 17 (#90) is deployed with
[section 9](#9-upgrading-postgresql-15-to-17), not with these commands.**

**A new `database` image tag on the same PostgreSQL major** (a pgSTAC patch
release, such as `v0.10.1` to `v0.10.2`) changes the image only: the schema of
an existing database stays at its old version until it is migrated. Take a
[backup](#backup) first, then, after `git pull`:

```bash
docker compose up -d --wait database
TOOL=ghcr.io/stac-utils/pgstac-pypgstac:$(docker compose config --images \
  | sed -n 's#^ghcr.io/stac-utils/pgstac:##p')
export PGUSER=$(docker compose exec -T database printenv PGUSER)
export PGPASSWORD=$(docker compose exec -T database printenv PGPASSWORD)
export PGDATABASE=$(docker compose exec -T database printenv PGDATABASE)
docker run --rm --network eoapi-network \
  -e PGHOST=database -e PGUSER -e PGPASSWORD -e PGDATABASE "$TOOL" pypgstac migrate
docker compose up -d --build
docker compose restart stac-api home
```

`pypgstac migrate` prints the new version. Restarting stac-api re-applies the
app role's pgSTAC access, since a migration can grant `CREATE` back to
`pgstac_ingest`. A tag on another PostgreSQL major never goes this way: it needs
an upgrade like section 9.

After the release that adds async process jobs (#349), rebuild both process
services, then restart home so nginx resolves the new process-api address:

```bash
docker compose up -d --build process-api process-worker
docker compose restart home
docker compose logs process-worker | grep ready
```

After the release that splits large polygons at ingestion (#292):

1. Re-ingest the GRHQ source with gis-pipeline. Features above 100 000
   vertices are stored as pieces (`split_source_gid`, `split_part`); the
   materialize trigger rebuilds each `.duckdb`.
2. Rebuild `grhq_water_union` (section 8, Step 5): `grhq_hr_06ae_rh_s` is one
   of the split tables.
3. Once `docker compose logs vector-api` shows the
   `Parquet schema warm-up: N of M collections scanned` line, run
   `make check-parquet-memory` and `make smoke-catalogs`. The `/postgis`
   entries of the probe are measured wherever the GRHQ tables exist. A FAIL on
   `grhq_hr_04ac_s_udh/items?limit=10000` alone is the known edge described in
   `vector-api/README.md` (Checking peak memory); any other FAIL is real.

### Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f chatbot-backend
docker compose logs -f caddy
```

### Backup

A backup is a custom-format dump of the whole database, the cluster roles
(which a database dump does not contain) and an inventory of the counts to
compare against after a restore. Keep backups outside the repository: the roles
file holds password hashes and must never be committed.

```bash
BACKUP_DIR=/srv/backups/agri-sdss   # any directory outside the repository
STAMP=$(date +%Y%m%d)
mkdir -p "$BACKUP_DIR"

# Whole database, custom format (what pgstac_restore reads). -T keeps the
# binary output intact; the container's PGUSER and PGDATABASE pick the superuser.
docker compose exec -T database pg_dump -Fc > "$BACKUP_DIR/agri_sdss_$STAMP.dump"

# Cluster roles, with password hashes: readable by the owner only
(umask 077; docker compose exec -T database pg_dumpall --roles-only \
  > "$BACKUP_DIR/roles_$STAMP.sql")

# Counts to diff after a restore (section 8)
docker compose exec -T database psql -X -f - < scripts/db_inventory.sql \
  > "$BACKUP_DIR/inventory_$STAMP.txt"

# DuckDB (file copy is safe when pipeline is not writing)
cp data/duckdb/eoapi.duckdb "$BACKUP_DIR/duckdb_$STAMP.duckdb"
```

**Dumps taken on pgSTAC 0.8.5 (release v2.0.1 and earlier) cannot be
restored.** Any restore of them loses `pgstac.searches`, and STAC search then
fails (#90). Keep them as archives only: the restore point of those releases is
a copy of the stopped data directory, as in
[section 9](#9-upgrading-postgresql-15-to-17).

### Changing the application role password

The `agri_sdss` role password is set once at first DB init. To rotate it after initial deployment:

```bash
# 1. Update DB_PASS in .env
# 2. Apply the new password to the running database
docker compose exec database psql -U postgres -d agri_sdss \
  -c "ALTER ROLE agri_sdss WITH PASSWORD 'your-new-password';"
# 3. Restart services so they pick up the new DB_PASS
docker compose up -d
```

### Republishing STAC items after an href change

Items already in pgSTAC keep the hrefs they were published with. process-api
skips republishing while a `<cog>.tif.stac.json` marker sits next to the COG,
so the markers must be removed before the next run:

```bash
find ./data/output/raster_cog -name '*.stac.json' -delete
```

The next `lidar-fetch` or `sentinel-fetch` execution for a given geometry then
republishes that item with corrected hrefs. Items whose process is never re-run
keep the old hrefs; to force the whole catalog, re-run the fetch processes for
each published geometry.

**gis-pipeline (`demo_collection`) needs its own pass.** Those items come from a
different codebase with no marker cache, so the sweep above does not touch them.
Re-run the pipeline's COG step to republish them. Rows already in the metadata
table also keep the old `file://` form in `file_url` — the `ON CONFLICT DO
UPDATE` at `pg_utils.py:1220` only rewrites rows that are re-inserted. Nothing
parses that column (`pg_utils.py:953` selects it into a GeoDataFrame untouched),
so this is cosmetic, but a one-off
`UPDATE <table> SET file_url = replace(file_url, 'file://', '')` cleans it.

This is also the fix for items published while `HOST_URL` was wrong (see the
[gate above](#2-environment-variables)): correct `.env` first, then run this
sweep so the next publish uses the right value.

---

## Domain migration summary

All changes needed when moving from self-signed to a real domain:

| File | Change |
| --- | --- |
| `.env` | `SITE_ADDRESS=ton-domaine.ca`, `ACME_EMAIL=<email>`, `HOST_URL=ton-domaine.ca`, `HOST_PROTOCOL=https` |

Then `docker compose up -d` to recreate the services with the new values.

Any STAC items published before the domain change carry hrefs built from the
old `HOST_URL` — run the
[republication sweep](#republishing-stac-items-after-an-href-change) afterward
to correct them.

---

## 8. Restoring a production database dump

This procedure restores a [backup](#backup) into a fresh database started from
the `database` image of `docker-compose.yml`: on a new server, after losing the
data directory, or during the [PostgreSQL upgrade](#9-upgrading-postgresql-15-to-17).
The dump must come from the pgSTAC version of that image: compare the
`pgstac_version` line of the backup's inventory with the `database` image tag.
A dump taken on pgSTAC 0.8.5 cannot be restored (see [Backup](#backup)); a
v.2.0.1 data directory is upgraded with section 9.

For a continuous connection to an existing PostgreSQL database (logical replication, foreign data wrapper) instead of one-off dumps, see [Database integration](data/guides/database_integration.md).

### Step 1 — start an empty database

```bash
docker compose down
# The data directory (PGDATA_PATH in .env, default ./data/pg/.pgdata) must be
# empty or absent. Move an existing one aside rather than deleting it.
docker compose up -d database
docker compose ps database   # wait for "healthy"
```

The first start creates the superuser, the `pgstac_*` roles and the app role
(`DB_USER`) from `.env`, the extensions and an empty pgSTAC schema. The restore
keeps object owners, so these role names must be the ones of the source. If the
source used other names, create the missing roles first from the `CREATE ROLE`
lines of `roles_<DATE>.sql`. Do not run the whole file: its `ALTER ROLE` lines
would overwrite the passwords set from `.env`.

### Step 2 — restore the dump

Run Steps 2 and 3 in one shell.

```bash
BACKUP_DIR=/srv/backups/agri-sdss                 # where the backup files are
TOOL=ghcr.io/stac-utils/pgstac-pypgstac:$(docker compose config --images \
  | sed -n 's#^ghcr.io/stac-utils/pgstac:##p')   # same tag as the database image
export PGUSER=$(docker compose exec -T database printenv PGUSER)
export PGPASSWORD=$(docker compose exec -T database printenv PGPASSWORD)
export PGDATABASE=$(docker compose exec -T database printenv PGDATABASE)

# The dump brings its own pgSTAC schema
docker compose exec -T database psql -X -v ON_ERROR_STOP=1 -c 'DROP SCHEMA pgstac CASCADE'

docker run --rm --network eoapi-network \
  -e PGHOST=database -e PGUSER -e PGPASSWORD -e PGDATABASE \
  -v "$BACKUP_DIR:/backup:ro" "$TOOL" \
  pgstac_restore /backup/agri_sdss_<DATE>.dump 2>&1 | tee "$BACKUP_DIR/restore_<DATE>.log"
grep -A1 'pg_restore: error' "$BACKUP_DIR/restore_<DATE>.log"
```

`pgstac_restore` runs `pg_restore` with the `search_path` pgSTAC's functions
need and keeps owners and privileges, so `public` tables stay owned by the app
role and ingestion can still replace them. The tool image runs as uid 1000: the
dump must be readable by it, which the default file mode is.

`pgstac_restore` always ends with `Restore complete.` and exit code 0, even
when `pg_restore` failed, so read the errors. Exactly one is expected:

- `function "pgstac_admin_owns" already exists with same argument types`: a
  `public` function the first start created, outside the dropped schema.

Any other error means a failed restore: keep the backup, empty the data
directory and start again from Step 1.

### Step 3 — analyze and compare

```bash
docker run --rm --network eoapi-network \
  -e PGHOST=database -e PGUSER -e PGPASSWORD -e PGDATABASE \
  "$TOOL" vacuumdb --analyze-in-stages
docker compose exec -T database psql -X -f - < scripts/db_inventory.sql \
  > "$BACKUP_DIR/inventory_<DATE>-restored.txt"
diff "$BACKUP_DIR/inventory_<DATE>.txt" "$BACKUP_DIR/inventory_<DATE>-restored.txt"
```

The diff is empty when nothing was written between the dump and its inventory.
Any other difference means a lost table, item, index or search result: do not
start the stack.

### Step 4 — start the stack

```bash
docker compose up -d
docker compose restart home
make smoke-catalogs
make smoke-browser-pages
```

The stac-api start re-applies the app role's pgSTAC access
(`stac-api/scripts/apply_pgstac_grants.sql`), which removes the direct grants
the dump brought back from the source.

### After a restore on a new server

The dump holds the database only. The files under `data/` (Parquet, COGs,
DuckDB indexes) come from a copy of the old server's `data/`, or are rebuilt
with the steps below.

### Step 5 — rebuild the GRHQ water union table

`scripts/build_grhq_water_union.py` merges all eligible GRHQ hydrological line and polygon tables into a single `public.grhq_water_union` table. This union is the data source for "distance from water" spatial queries in the SOM Calculator. The dump already holds it; rebuild it after re-ingesting GRHQ tables.

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

Run those three statements as the `agri_sdss` user (or `postgres` if the table owner needs to change):

```bash
docker compose exec database psql -U agri_sdss -d agri_sdss -c "
  DROP TABLE IF EXISTS public.grhq_water_union;
  ALTER TABLE public.grhq_water_union_new RENAME TO grhq_water_union;
"
docker compose exec database psql -U agri_sdss -d agri_sdss -c "
  CREATE INDEX CONCURRENTLY grhq_water_union_geom_idx
      ON public.grhq_water_union USING GIST(geometry);
"
```

`CREATE INDEX CONCURRENTLY` must run outside a transaction block, so it is issued as a separate command.

### Step 6 — run the gis-pipeline

Ingest all input files from `/data/input`:

```bash
docker compose run --rm gis-pipeline python3 -m gis_pipeline.main \
  --input /data/input \
  --crs 4326 \
  --collection agri_sdss_collection
```

The final log lines report `Processed`, `Errors`, and `Non_spatial_csv` counts. `Errors: 0` is the target. After a successful run, vector layers, COGs, and STAC items are all up to date. The pipeline automatically stamps `has_gee_data` on `som_field_boundaries` at the end of every run — no manual post-step needed.

### Step 7 — spatial index materialization (automatic + manual catch-up)

Any Parquet collection with a geometry column can be served from a persistent, RTree-indexed on-disk DuckDB table instead of a per-request `read_parquet()` scan, as soon as a `<collection>.duckdb` file exists for it next to its `.parquet` file — `vector-api` auto-discovers it, no config needed.

**This is automatic** for every table gis-pipeline writes, regardless of format or row count: right after step 6 writes a collection's Parquet file, gis-pipeline builds its spatial index and notifies `vector-api` to pick it up — no restart required.

**One-time manual catch-up** is needed for collections that already existed before this automatic trigger was added — auto-discovery only takes effect once a `.duckdb` file exists; it doesn't retroactively index anything. `make check-materialized` lists the large
geometry collections that still have no usable `.duckdb`; run the build script once per
collection it lists:

```bash
docker compose run --rm \
  -v "$(pwd)/scripts/build_duckdb_spatial_index.py:/tmp/build_duckdb_spatial_index.py:ro" \
  vector-api \
  python3 /tmp/build_duckdb_spatial_index.py --collection <collection_id>
```

The script builds into `<collection_id>.duckdb.new`, atomically renames it over `<collection_id>.duckdb`, and notifies `vector-api`'s `/invalidate` endpoint so it drops any cached connection and picks up the fresh file on the next request — no restart needed. If `vector-api` is unreachable when the script runs, it prints a warning and `docker compose restart vector-api` remains available as a manual fallback.

To confirm indexing is working and didn't change results, compare a bbox filter before and after:

```bash
docker compose run --rm \
  -v "$(pwd)/scripts/benchmark_duckdb_bbox.py:/tmp/benchmark_duckdb_bbox.py:ro" \
  vector-api \
  python3 /tmp/benchmark_duckdb_bbox.py \
  --collection <collection_id> \
  --bbox <minx> <miny> <maxx> <maxy> \
  --trials 10
```

`numberMatched` must be identical between the `read_parquet()` and materialized runs; only the timing should differ. A `MISMATCH` means the materialized table is stale relative to the source Parquet file — rerun the build command above.

---

## 9. Upgrading PostgreSQL 15 to 17

The release after v.2.0.1 moves the `database` image from pgSTAC 0.8.5 on
PostgreSQL 15 to pgSTAC 0.10.1 on PostgreSQL 17 (#90). PostgreSQL 17 cannot
open a PostgreSQL 15 data directory: once that release is checked out,
`database` refuses the existing directory and stays down until this procedure
has run. Never deploy that release with a plain `git pull` and `up`.

A dump taken on pgSTAC 0.8.5 cannot be restored (see [Backup](#backup)), so the
upgrade migrates pgSTAC to 0.10.1 on PostgreSQL 15 first, dumps that, and
restores it into a fresh PostgreSQL 17 database. The rollback is an untouched
copy of the stopped PostgreSQL 15 data directory, never a dump.

### Prerequisites

- **Disk:** free space for two more copies of the data directory (the rollback
  copy and the migrated directory) plus the dump. Check with
  `docker run --rm -v "$PWD/data/pg:/pg:ro" alpine du -sh /pg` and `df -h .`.
- **Images,** pulled before the window:
  `docker pull ghcr.io/stac-utils/pgstac:v0.10.1` and
  `docker pull ghcr.io/stac-utils/pgstac-pypgstac:v0.10.1`.
- **Host backup jobs:** a cron job that runs `pg_dump` with a client installed
  on the host fails against PostgreSQL 17 when that client is older. Look in
  `crontab -l` and `/etc/cron.d`, and move such a job to the
  [Backup](#backup) commands, which run `pg_dump` inside the container.
- **Rehearsal** done on a copy of production (below), with its step durations
  to size the maintenance window.

### Rehearsal on a copy of production

Rehearse the whole procedure before the window, on another machine:

1. On production, take a physical copy of the data directory during a short
   stop. The archive holds every row and the password hashes, so only its owner
   can read it:

   ```bash
   PGDIR=./data/pg/.pgdata                # PGDATA_PATH in .env, if set
   BACKUP_DIR=/srv/backups/agri-sdss
   mkdir -p "$BACKUP_DIR"
   docker compose stop
   (umask 077; docker run --rm -v "$(cd "$(dirname "$PGDIR")" && pwd):/pg:ro" alpine \
     tar -C /pg -czf - "$(basename "$PGDIR")" \
     > "$BACKUP_DIR/pgdata-pg15-$(date +%Y%m%d).tar.gz")
   docker compose start && docker compose restart home
   ```

2. On the rehearsal machine, extract it into a folder of its own, so the local
   data directory stays untouched, and point the stack at it:

   ```bash
   mkdir -p data/pg/rehearsal
   docker run --rm -i -v "$PWD/data/pg/rehearsal:/pg" alpine tar -C /pg -xzf - \
     < pgdata-pg15-<DATE>.tar.gz
   ```

   Set `PGDATA_PATH=./data/pg/rehearsal/.pgdata` in `.env` for the rehearsal
   (and use it as `PGDIR` in Step 1). `POSTGRES_USER` and `DB_USER` must have
   the production names, since the restore keeps owners. Check out the commit
   production runs and start `database`. The copy carries production's
   passwords, so set them to the local `.env` ones (the socket connection needs
   none), and confirm pgSTAC 0.8.5:

   ```bash
   docker compose up -d database
   docker compose exec -T database sh -c \
     'psql -X -q -v ON_ERROR_STOP=1 -v su="$PGUSER" -v su_pass="$PGPASSWORD" -v app="$DB_USER" -v app_pass="$DB_PASS"' <<'SQL'
   ALTER ROLE :"su" PASSWORD :'su_pass';
   ALTER ROLE :"app" PASSWORD :'app_pass';
   SQL
   docker compose exec -T database psql -X -qAt -c 'SELECT pgstac.get_version()'
   ```

3. Run the cutover steps below exactly as written, recording the duration of
   each step and every error printed. Restore `PGDATA_PATH` afterwards.

Proceed to production only when the restore printed nothing but the five
expected errors and the inventory diff shows only the two version lines.

### Cutover

Run every step from the repository root, in one shell. Step 1 extracts the
helper file `scripts/db_inventory.sql` from the release, because the older
checkout does not have it.

**Step 1: variables, helpers and the "before" inventory.**

```bash
NEW_TAG=<release tag>                  # the release with pgstac:v0.10.1
PGDIR=./data/pg/.pgdata                # PGDATA_PATH in .env, if set
BACKUP_DIR=/srv/backups/agri-sdss      # outside the repository
TOOL=ghcr.io/stac-utils/pgstac-pypgstac:v0.10.1
STAMP=$(date +%Y%m%d)
PARENT=$(cd "$(dirname "$PGDIR")" && pwd); NAME=$(basename "$PGDIR")
mkdir -p "$BACKUP_DIR"
git fetch --tags
git rev-parse HEAD > "$BACKUP_DIR/previous-commit-$STAMP.txt"   # rollback target
git show "$NEW_TAG:scripts/db_inventory.sql" > "$BACKUP_DIR/db_inventory.sql"

docker compose config --services | grep -vx database | xargs docker compose stop
docker compose exec -T database psql -X -f - < "$BACKUP_DIR/db_inventory.sql" \
  > "$BACKUP_DIR/inventory-before-$STAMP.txt"
cat "$BACKUP_DIR/inventory-before-$STAMP.txt"   # pgstac_version | 0.8.5
```

Both `search_*` counts must be below `search_limit`. If one equals it, raise
`search_limit` in `$BACKUP_DIR/db_inventory.sql`, the copy every step of this
section uses, and take the inventory again.

**Step 2: stop the database and take the rollback copy.**

```bash
docker compose down
docker run --rm -v "$PARENT:/pg" alpine cp -a "/pg/$NAME" /pg/.pgdata-v201-pg15
docker run --rm -v "$PARENT:/pg:ro" alpine sh -c \
  "find /pg/$NAME | wc -l; find /pg/.pgdata-v201-pg15 | wc -l"   # equal counts
```

Nothing touches `.pgdata-v201-pg15` from here on.

**Step 3: migrate pgSTAC to 0.10.1, still on PostgreSQL 15.**

```bash
docker compose up -d database
docker compose ps database   # wait for "healthy"
export PGUSER=$(docker compose exec -T database printenv PGUSER)
export PGPASSWORD=$(docker compose exec -T database printenv PGPASSWORD)
export PGDATABASE=$(docker compose exec -T database printenv PGDATABASE)
docker run --rm --network eoapi-network \
  -e PGHOST=database -e PGUSER -e PGPASSWORD -e PGDATABASE "$TOOL" pypgstac migrate
docker compose exec -T database psql -X -qAt \
  -c 'SELECT pgstac.get_version()' -c 'SELECT count(*) FROM pgstac.query_queue'
```

The migration prints `0.10.1` and the check prints `0.10.1` then `0`. If the
queue count is not 0, run
`docker compose exec -T database psql -X -c 'CALL pgstac.run_queued_queries()'`
and check again before the dump.

**Step 4: dump the migrated database.**

```bash
DUMP=agri_sdss-pgstac-0.10.1-pg15-$STAMP.dump
docker compose exec -T database pg_dump -Fc > "$BACKUP_DIR/$DUMP"
(umask 077; docker compose exec -T database pg_dumpall --roles-only \
  > "$BACKUP_DIR/roles-$STAMP.sql")
```

**Step 5: set the migrated directory aside and check out the release.**

```bash
docker compose down
docker run --rm -v "$PARENT:/pg" alpine mv "/pg/$NAME" /pg/.pgdata-pg15-migrated
git checkout "$NEW_TAG"
```

**Step 6: start a fresh PostgreSQL 17 database.**

```bash
docker compose up -d database
docker compose ps database   # wait for "healthy"
docker compose exec -T database psql -X -qAt \
  -c "SELECT pgstac.get_version(), current_setting('server_version')"   # 0.10.1|17.x
```

**Step 7: restore.**

```bash
docker compose exec -T database psql -X -v ON_ERROR_STOP=1 -c 'DROP SCHEMA pgstac CASCADE'
docker run --rm --network eoapi-network \
  -e PGHOST=database -e PGUSER -e PGPASSWORD -e PGDATABASE \
  -v "$BACKUP_DIR:/backup:ro" "$TOOL" \
  pgstac_restore "/backup/$DUMP" 2>&1 | tee "$BACKUP_DIR/restore-$STAMP.log"
grep -A1 'pg_restore: error' "$BACKUP_DIR/restore-$STAMP.log"
```

`pgstac_restore` exits 0 whatever happens, so read the errors. Exactly these
five are expected:

- `function "pgstac_admin_owns" already exists with same argument types`: a
  `public` function the fresh database created, outside the dropped schema.
- Four `GRANT ALL ON FUNCTION pgstac.unaccent... TO pgstac_ingest` failures
  (`unaccent(text)`, `unaccent(regdictionary, text)`, `unaccent_init(internal)`,
  `unaccent_lexize(internal, internal, internal, internal)`): the migration
  installed `unaccent` in `pgstac` on PostgreSQL 15, while the fresh database
  has it in `public`. Accent-insensitive search still works.

Any other error: go to [Rollback](#rollback).

**Step 8: analyze and compare.**

```bash
docker run --rm --network eoapi-network \
  -e PGHOST=database -e PGUSER -e PGPASSWORD -e PGDATABASE \
  "$TOOL" vacuumdb --analyze-in-stages
docker compose exec -T database psql -X -f - < "$BACKUP_DIR/db_inventory.sql" \
  > "$BACKUP_DIR/inventory-after-$STAMP.txt"
diff "$BACKUP_DIR/inventory-before-$STAMP.txt" "$BACKUP_DIR/inventory-after-$STAMP.txt"
```

The diff shows only `pgstac_version` (0.8.5 to 0.10.1) and `server_version`
(15 to 17): the counts, owners, indexes and the item ids of the two searches
are unchanged. Any other line: go to [Rollback](#rollback).

**Step 9: start the stack.**

```bash
docker compose up -d --build
docker compose restart home
```

The stac-api start gives the app role its pgSTAC access through
`pgstac_ingest` and removes the direct grants the dump restored.

### Checks after the cutover

```bash
docker compose ps                                       # every service healthy
docker compose logs stac-api | grep 'pgstac grants applied'
make smoke-catalogs
make smoke-browser-pages

# A vector tile from PostGIS and a raster tile from a COG
# (<file>: a COG listed by /raster-api/collections)
docker run --rm --network eoapi-network curlimages/curl:latest -s -o /dev/null \
  -w '%{http_code} %{size_download}\n' \
  'http://home:8080/vector-api/postgis/collections/public.couverture_pedologique_2026_01_couverture_p_cbc3c8/tiles/WebMercatorQuad/0/0/0'
docker run --rm --network eoapi-network curlimages/curl:latest -s -o /dev/null \
  -w '%{http_code} %{size_download}\n' \
  'http://home:8080/raster-api/cog/tiles/WebMercatorQuad/0/0/0.png?url=/data/<file>.tif'
```

Both tiles answer 200 with a non-zero size. The next publication by
gis-pipeline or process-api confirms that new items can be written.

### Rollback

```bash
docker compose down
docker run --rm -v "$PARENT:/pg" alpine sh -c \
  "if [ -e /pg/$NAME ]; then mv /pg/$NAME /pg/.pgdata-pg17-failed; fi; cp -a /pg/.pgdata-v201-pg15 /pg/$NAME"
git checkout "$(cat "$BACKUP_DIR/previous-commit-$STAMP.txt")"
docker compose up -d --build
docker compose restart home
docker compose exec -T database psql -X -f - < "$BACKUP_DIR/db_inventory.sql" \
  | diff "$BACKUP_DIR/inventory-before-$STAMP.txt" -   # empty
```

The rollback copies `.pgdata-v201-pg15` instead of moving it, so a second
attempt starts from the same untouched copy.

### Cleanup

A few days after a cutover without problems, delete `.pgdata-v201-pg15`,
`.pgdata-pg15-migrated` and `.pgdata-pg17-failed` if present (through the same
`alpine` container, since they belong to the database user), and the dump.

---

## First-time deploy on a server with existing data

An install from before the `agri_sdss` rename keeps its data in a database named
`postgres` (`POSTGRES_DBNAME=postgres`). Move it to the new layout with the
[backup](#backup) and [restore](#8-restoring-a-production-database-dump)
procedures, not with a plain-SQL dump loaded by `psql`, which breaks the pgSTAC
schema:

1. Bring the install to the pgSTAC version of the current `database` image
   first: a dump taken on an older pgSTAC cannot be restored. An install on
   pgSTAC 0.8.5 is upgraded with section 9.
2. Take a backup with the old `.env`: the dump comes from the `postgres`
   database.
3. Stop the stack, move the data directory aside, and update `.env` with the
   new credentials (`POSTGRES_DBNAME=agri_sdss`, `DB_USER`, `DB_PASS`, …).
4. Restore with section 8. `pg_restore` loads the dump into `agri_sdss` whatever
   the source database was called.
5. Such an install had no app role, so its `public` tables belong to the
   superuser and ingestion could not replace them. Hand them to `DB_USER`:

   ```bash
   docker compose exec -T database sh -c 'psql -X -v ON_ERROR_STOP=1 -v app="$DB_USER"' <<'SQL'
   SELECT format('ALTER TABLE public.%I OWNER TO %I', tablename, :'app')
   FROM pg_tables
   WHERE schemaname = 'public' AND tableowner <> :'app' AND tablename <> 'spatial_ref_sys'
   \gexec
   SQL
   ```

Then: `docker compose restart caddy`. CORS and all internal service URLs update automatically.
