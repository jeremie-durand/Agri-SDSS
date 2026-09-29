# CLAUDE.md — stac-api

Service guide for `stac-api`. It specializes the [root CLAUDE.md](../CLAUDE.md)
and wins wherever the two differ; everything the root file says still applies
unless overridden here.

## Service Overview

Stock `stac-fastapi.pgstac` (STAC API 1.0.0) served from the pgSTAC schema in
the shared PostgreSQL. It runs on Python 3.11, port 8081 (`expose:` only), with
public prefix `/stac-api`. The only custom code is `src/app.py`, a thin wrapper
that silences a FastAPI deprecation before importing
`stac_fastapi.pgstac.app`.

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
docker compose run --rm stac-api pytest stac_api/test/test_app.py -v

# Apply a src/ or requirements change, then restart home
docker compose up -d --build stac-api
docker compose restart home
```

## Structure

```text
src/app.py               Warning filter + ORJSONResponse swap, then re-exports
                         stac_fastapi.pgstac.app:app
scripts/entrypoint.sh    Waits for the DB, applies pgstac GRANTs as admin, then runs
                         uvicorn with up to 5 restart attempts
test/                    Bind-mounted at /app/stac_api/test
  conftest.py            stac_integration_client + sample collection/item fixtures
  db_utils.py            Admin-credential cleanup of test collections
.coveragerc              Coverage scoped to stac_api
```

## How It Is Built

- **Behaviour comes from pinned packages**, not our code:
  `stac-fastapi.pgstac`, `.api`, `.types` and `.extensions` in
  `requirements-stac-api.txt`. Configuration is through that library's env
  vars (`PG*`, `CORS_*`, `ENABLE_TRANSACTIONS_EXTENSIONS`); there is no config
  module of ours.
- `app.py` must stay import-order sensitive: `configure_warnings()` runs
  before any `stac_fastapi` import, and `_OrjsonResponse` replaces
  `stac_fastapi.api.models.JSONResponse` before `stac_fastapi.pgstac.app` builds
  its routes. Keep new patches in the same place, before that final import.
  Remove the swap once stac-fastapi drops `ORJSONResponse`.
- uvicorn runs with `--root-path ${APP_ROOT_PATH}` (`/stac-api`), which is how
  self-links carry the public prefix. `STAC_API_URL` is set in compose but is
  **not read** by stac-fastapi. It is the URL other services use to reach this
  one.
- `CORS_ORIGINS` comes from `.env`, where the default is `*`. That is a
  deliberate public read API.

## Database Roles

- The API runs as the app role (`PGUSER` = `DB_USER`, DML only).
- On every start, `entrypoint.sh` connects as the superuser
  (`PGSTAC_ADMIN_USER`/`PGSTAC_ADMIN_PASS`) and GRANTs the app role access to
  all `pgstac` tables, sequences and functions. It is idempotent. A failed
  GRANT only prints a warning, so check the logs when the API cannot read
  pgstac.
- The app role cannot delete a **collection**: pgstac's delete trigger drops a
  partition, which needs ownership, so `DELETE /collections/{id}` fails with
  an insufficient-privilege error. Item create, update and delete work.

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
  role can do in `entrypoint.sh`.

## Testing

| Marker | File | What it needs |
| --- | --- | --- |
| `unit` | `test_app.py`, `test_stac_app_routes.py`, `test_conftest_behaviour.py` | nothing live |
| `integration` | `test_stac_integration.py` | the **real** pgstac database |

- Integration tests run against the same database the stack serves. They
  create `test-integration-collection-<uuid>` and an item, then clean up
  through `db_utils.admin_delete_collection()` with the admin credentials. If
  those are unset, the test collection **leaks** into the live catalog with a
  warning. Never point the suite at a production database.
- `stac_integration_client` skips only when the database is unreachable
  (`OSError`). Any other startup failure fails the run on purpose.
- Use `unique_suffix` for every id a test creates, so runs never collide.
- There is no i18n: stac-fastapi errors are English, and this service is not
  wired to `agri_i18n`.
