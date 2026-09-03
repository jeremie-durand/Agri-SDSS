# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Running services

```bash
# Start all services
docker compose up -d

# Start a specific service
docker compose up -d stac-api
```

### Testing

```bash
# All services
make test-all

# Individual services
make test-gis-pipeline
make test-stac-api
make test-vector-api
make test-raster-api
make test-process-api
make test-chatbot

# Single test file or test (inside container)
docker compose run --rm stac-api pytest stac_api/test/test_foo.py::test_bar -v

# Auxiliary targets (not part of test-all)
make test-caddy         # Rate-limit integration tests (hot-reloads Caddyfile.test)
make lint-dockerfiles   # hadolint on the chatbot Dockerfiles
make lint-nginx         # nginx -t on the generated home and chatbot-frontend configs
make scan-secrets       # Trivy secret scan over the repo
make generate-args      # Regenerate gis-pipeline/docs/ARGS.md from the CLI parser
```

## Architecture

Agri-SDSS is a geospatial data platform for sustainable agriculture research in Quebec. It follows a pipeline → storage → API → frontend pattern. The authoritative service/port table, system diagram, and technology choices are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

### Shared infrastructure

- **PostgreSQL + PostGIS** (pgSTAC image) — STAC metadata + vector features. Docker port 5432, local port 5439.
- **DuckDB** — in-process analytics on GeoParquet files at `DUCKDB_DATABASE`.
- **Network**: services communicate via the Docker Compose network using service names (e.g., `database`, `stac-api`)

The `home` nginx is the single entry point for all frontends — proxy routes, nav injection, and the chatbot ↔ map `postMessage` bridge are documented in [frontend/home/README.md](frontend/home/README.md).

### Key source paths

`gis-pipeline` and `vector-api` have a `src/` directory added to `pythonpath` in `pytest.ini`; other services do not. Each backend service has its own `test/` directory, `Dockerfile.<service>`, `requirements-<service>.txt`, and `requirements-<service>-test.txt`. Tests are marked with `@pytest.mark.unit`, `@pytest.mark.integration`, or `@pytest.mark.mocked`.

## Configuration

- Environment variables are defined in `.env`.
- Variables used by CI (`action.yml`) are noted.
- Integrated data sources: [docs/data/CATALOG.md](docs/data/CATALOG.md).

### API URLs

| Variable | Example | Description |
| --- | --- | --- |
| `STAC_API_URL` | `http://stac-api:8081` | STAC API base URL (internal Docker service name), used by gis-pipeline to publish STAC items |

### PostgreSQL / PostGIS

Two credentials exist (least-privilege model — see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md#database-credential-model)):

| Variable | Example / CI | Description |
| --- | --- | --- |
| `POSTGRES_USER` | `postgres` | Superuser — Docker init, healthcheck, and backups only |
| `POSTGRES_PASS` | _(generated)_ | Superuser password (`POSTGRES_PASSWORD` in CI) |
| `DB_USER` | `agri_sdss` | App role used by all backend services (SELECT/INSERT/UPDATE/DELETE) |
| `DB_PASS` | _(generated)_ | App role password |
| `POSTGRES_DBNAME` | `agri_sdss` | Database name (`POSTGRES_DB` in CI) |
| `POSTGRES_HOST` | `database` | Hostname — use `database` in Docker, `localhost` locally |
| `POSTGRES_PORT` | `5432` | Port — use `5432` in Docker, `5439` locally |
| `POSTGRES_LOCAL_PORT` | `5439` | Host-side port mapping for local connections |

### DuckDB

| Variable | Example | Description |
| --- | --- | --- |
| `DUCKDB_DATABASE` | `/data/duckdb/eoapi.duckdb` | Path to the DuckDB database file |
| `DUCKDB_DATA_DIR` | `/data/duckdb` (`/tmp` in CI) | Directory for GeoParquet files written by the pipeline |

### Ports

| Variable | Default | Description |
| --- | --- | --- |
| `STAC_API_PORT` | `8081` | stac-api |
| `RASTER_API_PORT` | `8082` | raster-api |
| `VECTOR_API_PORT` | `8083` | vector-api |
| `PROCESS_API_PORT` | `5000` | process-api |
| `HOME_PORT` | `8084` | home frontend (unified entry point) |
| `CHATBOT_BACKEND_PORT` | `8005` | chatbot-backend |
| `CHATBOT_FRONTEND_PORT` | `3001` | chatbot-frontend (direct access) |
| `STAC_BROWSER_PORT` | `8085` | stac-browser (direct access) |
| `VECTOR_API_CORS_ORIGINS` | _(empty)_ | Comma-separated allowed CORS origins for vector-api; empty blocks all cross-origin requests |

### OpenEO / Copernicus

| Variable | Description |
| --- | --- |
| `OPENEO_REFRESH_TOKEN` | OIDC refresh token for Copernicus Data Space — expires ~30 days; regenerate with `./process-api/scripts/get_openeo_token.sh` |

## Claude guidelines

- Understand the pipeline before modifying code
- Keep changes minimal and scoped
- Always update or add tests when modifying logic
- Reuse existing utilities and patterns

### Key Patterns to Follow

- Type hints required for all code
- Functions must be focused and small
- Line length: 88 chars maximum
- PEP 8 naming (snake_case for functions/variables)
- Class names in PascalCase
- Constants in UPPER_SNAKE_CASE
- Document with docstrings, avoid comments
- Use f-strings for formatting
- User-facing messages go through `_()` from `agri_i18n` with **literal** msgids — never
  f-strings, which pybabel cannot extract. Interpolate after the lookup:
  `_("Invalid geometry: {error}").format(error=exc)`. See [docs/I18N.md](docs/I18N.md)
- Log in English (`logger.warning("...: %s", exc)`) even when the raised message is translated
- Use `is not` operator rather than `not ... is`
  - Correct:

    ```python
    if foo is not None:
    ```

  - Wrong:

    ```python
    if not foo is None:
    ```

### Testing guidelines

- Unit tests for pure logic
- Integration tests for API endpoints
- Prefer mocked tests when external services are involved

### Branching strategy

- `develop` — integration branch (PRs target here)
- `main` — production

Commit prefixes (conventional style): `feat:`, `fix:`, `docs:`, `test:`, `refacto:`, `chore:`

## CI

GitHub Actions (`.github/workflows/action.yml`) runs on PR/push to main/develop:

1. Validates `ARGS.md` is in sync with CLI arguments
2. Validates the i18n catalogs (`python -m agri_i18n.check`)
3. Validates the nginx configs (`make lint-nginx`)
4. Builds per-service images (`gis-pipeline`, `stac-api`, `vector-api`, `raster-api`, `process-api`, `chatbot-backend`)
5. Starts the database, then runs `make test-all`

### Automation

- **Dependabot** (`.github/dependabot.yml`) — Monday 06:00 America/Montreal; pip + docker per service, docker-compose and GitHub Actions at root; one PR per dependency update
- **Security scans** (`security.yml`) — Trivy secret scan on push/PR; CVE scans and override verification only on the weekly Monday cron and manual `workflow_dispatch`
- **Chatbot release watcher** (`chatbot-release-watcher.yml`) — daily check of OpenGeo-AI-Assistant releases; auto-opens a PR bumping `CHATBOT_VERSION` in all four pinned files
