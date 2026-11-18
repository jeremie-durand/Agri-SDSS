# CLAUDE.md — stac-api

Service guide for `stac-api`. It specializes the [root CLAUDE.md](../CLAUDE.md)
and wins wherever the two differ; everything the root file says still applies
unless overridden here.

## Service Overview

Stock `stac-fastapi.pgstac` (STAC API 1.0.0) served from the pgSTAC schema in
the shared PostgreSQL. It runs on Python 3.13, port 8081 (`expose:` only), with
public prefix `/stac-api`. The only custom code is `src/app.py`, which re-exports
the upstream `create_app` factory that uvicorn starts with `--factory`.

- Endpoints and search examples: [README.md](README.md). Where it disagrees
  with the code or the live OpenAPI at `/stac-api/api`, trust those, and fix
  the doc when you touch that area.
- Publishers: gis-pipeline (`StacApiClient`) and process-api (Sentinel-2 and
  LiDAR processes) call `http://stac-api:8081` directly. Readers: STAC
  Browser, the chatbot, the home map.

## Common Commands

Run from the repo root.

```bash
make test-stac-api        # Rebuilds the image, runs the suite with coverage

# Single test — test/ is bind-mounted, so no rebuild needed for test edits
docker compose run --rm stac-api pytest stac_api/test/test_stac_app_routes.py -v

# Apply a src/ or requirements change, then restart home
docker compose up -d --build stac-api
docker compose restart home
```

## Structure

```text
src/app.py               Re-exports the upstream create_app factory
                         (uvicorn stac_api.app:create_app --factory)
scripts/entrypoint.sh    Waits for the DB, runs apply_pgstac_grants.sql as admin,
                         then uvicorn with up to 5 restart attempts
scripts/apply_pgstac_grants.sql
                         App role -> pgstac_ingest, CREATE revoked, direct grants removed
test/                    Bind-mounted at /app/stac_api/test
  conftest.py            stac_integration_client + sample collection/item fixtures
  db_utils.py            Admin and app-role connections, admin cleanup of test collections
.coveragerc              Coverage scoped to stac_api
```

## How It Is Built

- **Behaviour comes from pinned packages**, not our code:
  `stac-fastapi.pgstac`, `.api`, `.types` and `.extensions` in
  `requirements-stac-api.txt`. Configuration is through that library's env
  vars (`PG*`, `CORS_*`, `ENABLE_TRANSACTIONS_EXTENSIONS`); there is no config
  module of ours.
- stac-fastapi 7 has no module-level `app`: each `create_app()` call builds
  a new app from the environment. `stac_api.app:create_app` is the one entry
  point for uvicorn, the tests and `make smoke-entrypoints`, so a future patch
  goes there, as a `create_app` that wraps the upstream one.
- uvicorn runs with `--root-path ${APP_ROOT_PATH}` (`/stac-api`), which is how
  self-links carry the public prefix. `STAC_API_URL` is set in compose but is
  **not read** by stac-fastapi. It is the URL other services use to reach this
  one.
- `CORS_ORIGINS` comes from `.env`, where the default is `*`. That is a
  deliberate public read API.

## Database Roles

- The API runs as the app role (`PGUSER` = `DB_USER`). It reaches pgSTAC only
  as a member of pgSTAC's `pgstac_ingest` role. pgSTAC grants its own objects
  to that role, migrations included, and keeps its configuration tables
  (`queryable_wrappers`, `queryable_index_template`) out of it.
- On every start, `entrypoint.sh` runs `scripts/apply_pgstac_grants.sql` as the
  superuser (`PGSTAC_ADMIN_USER`/`PGSTAC_ADMIN_PASS`), in one transaction. It
  grants `pgstac_ingest`, revokes `CREATE ON SCHEMA pgstac` from
  `pgstac_ingest`, and revokes every direct `pgstac` grant and default
  privilege of the app role, which older releases and restored dumps carry. It
  is idempotent. A failure only prints a warning, so check the logs when the
  API cannot read pgstac.
- `CREATE` stays revoked because pgSTAC calls PostGIS unqualified under
  `search_path pgstac, public`. A role that can create in `pgstac` can shadow
  those functions and run code with the rights of pgSTAC's functions or of a
  migration. A pgSTAC migration grants `CREATE` back, so the revoke runs at
  every start. `scripts/create_app_role.sh` applies the same membership and
  revoke at first init.
- The app role can delete a populated collection, as publishers need. The
  integration tests still clean up through `db_utils.admin_delete_collection()`,
  so a failed test never leaks a collection.

## Security

`ENABLE_TRANSACTIONS_EXTENSIONS=TRUE` enables the Transactions and bulk-items
endpoints:

- `POST /collections`
- `PUT`/`PATCH`/`DELETE /collections/{id}`
- `POST /collections/{id}/items` and `/bulk_items`
- `PUT`/`PATCH`/`DELETE` on items

gis-pipeline and process-api need them. The API itself has no auth; the
public path is made read-only in home nginx (`frontend/home/scripts/entrypoint.sh`):

- `location /stac-api/` allows only `GET`, `HEAD` and `OPTIONS`. Anything else
  returns 403.
- `location = /stac-api/search` also allows `POST`, because a CQL2 search is a
  read.

Keep it that way:

- Publishers must use the internal URL (`http://stac-api:8081`). A publisher
  pointed at the public origin gets 403.
- A new **read** route that needs `POST` needs its own exact-match `location`
  in home nginx, like `/search`. Never loosen the `/stac-api/` block.
- Anything on the Docker network can still write, so never widen what the app
  role can do in `apply_pgstac_grants.sql` or `entrypoint.sh`.

## Testing

| Marker | File | What it needs |
| --- | --- | --- |
| `unit` | `test_stac_app_routes.py`, `test_conftest_behaviour.py` | nothing live |
| `integration` | `test_stac_integration.py` | the **real** pgstac database |

- Integration tests run against the same database the stack serves. They
  create `test-integration-*-<suffix>` collections with items, then clean up
  through `db_utils.admin_delete_collection()` with the admin credentials.
  Tests that need cleanup skip when those credentials are unset. Never point
  the suite at a production database.
- The privilege tests run `apply_pgstac_grants.sql` through `psql` as the
  admin, as a start does. One of them grants `CREATE` back to `pgstac_ingest`
  first, to check that the file revokes it, and revokes it again in `finally`.
  Another seeds the direct grants a restored dump carries. They run the copy
  of the file baked into the image, so after editing it use
  `make test-stac-api` or `docker compose run --build`.
- `stac_integration_client` skips only when the database is unreachable
  (`OSError`). Any other startup failure fails the run on purpose.
- Use `unique_suffix` for every id a test creates, so runs never collide.
- There is no i18n: stac-fastapi errors are English, and this service is not
  wired to `agri_i18n`.
