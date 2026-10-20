# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.
This file holds the rules shared by the whole platform; each microservice keeps
its own `CLAUDE.md` for service-specific detail.

Work from inside the service directory you are changing, and read that service's
`CLAUDE.md` first — it wins over this file wherever the two differ. Claude Code
loads a nested `CLAUDE.md` automatically when it touches files in that subtree,
but read it up front when planning a change, before opening any file.

| Service | Service guide |
| --- | --- |
| `gis-pipeline` | [gis-pipeline/CLAUDE.md](gis-pipeline/CLAUDE.md) |
| `chatbot` | [chatbot/CLAUDE.md](chatbot/CLAUDE.md) |
| `stac-api` | [stac-api/CLAUDE.md](stac-api/CLAUDE.md) |
| `vector-api` | [vector-api/CLAUDE.md](vector-api/CLAUDE.md) |
| `raster-api` | [raster-api/CLAUDE.md](raster-api/CLAUDE.md) |
| `process-api` | [process-api/CLAUDE.md](process-api/CLAUDE.md) |
| `frontend/home` | [frontend/home/CLAUDE.md](frontend/home/CLAUDE.md) |
| `agri_i18n` | — [docs/I18N.md](docs/I18N.md) |
| `caddy` | [caddy/CLAUDE.md](caddy/CLAUDE.md) |

A `—` means no service guide yet: fall back to this file plus the linked README.
When a service gains rules of its own, create its `CLAUDE.md` and update this
table — do not add service-specific rules here.

## Project Overview

Agri-SDSS is a geospatial data platform for sustainable agriculture research in
Quebec, built as a **pipeline → storage → API → frontend** chain. Services, ports,
data flow and technology choices are in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md); deployment, credentials and restore
procedures in [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md); integrated data sources in
[docs/data/CATALOG.md](docs/data/CATALOG.md). Read the relevant one before relying
on a detail from memory.

User-facing API messages are **French by default** (see [Internationalization](#internationalization)).

## Git Workflow

Branches and commit prefixes are in
[docs/CONTRIBUTING.md](docs/CONTRIBUTING.md#submitting-changes); PRs target
`develop`.

- **Claude never commits, pushes or opens PRs.** Leave changes uncommitted in the
  working tree and let the developer do it; create a branch only when asked in
  that turn.

CI (`.github/workflows/action.yml`) checks `ARGS.md` sync, i18n catalogs, nginx
configs, image builds, the stac-browser smoke test and `make test-all`.

## Common Commands

### Ops

```bash
docker compose up -d              # Start all services
docker compose up -d <service>    # Start one service
docker compose build              # Rebuild images (make build also creates data dirs)
docker compose logs -f <service>  # Follow logs
make smoke-entrypoints            # Verify every service entrypoint still imports
make smoke-stac-browser           # Start stac-browser and probe /stac/, its config and bundle

# home has no published port — reach it from inside the Docker network
docker run --rm --network eoapi-network curlimages/curl:latest -sI http://home:8080/
```

A `git pull` alone does not update a running service: images carry the code, so
rebuild the changed service (`docker compose up -d --build <service>`).

Recreating any API container (`stac-api`, `vector-api`, `raster-api`,
`process-api`) changes its IP, and `home` nginx keeps the old one, so every
proxied request to that API returns 502. Run `docker compose restart home`
afterwards. This includes containers recreated as dependencies, for example by
`make test-chatbot` or a `docker compose run --build`.

### Tests

```bash
make test-all             # Everything CI runs
make test-<service>       # gis-pipeline | stac-api | vector-api | raster-api |
                          # process-api | chatbot | i18n
make test-repo-consistency  # Guards the /cog route duplicated across 4 files
make test-caddy           # Rate-limit integration tests (hot-reloads Caddyfile.test)

# Single test file or test (inside the service container)
docker compose run --rm stac-api pytest stac_api/test/test_foo.py::test_bar -v
```

Each service runs its own container because base images and Python versions
differ; host-side `pytest` is scoped to `agri_i18n` by `pytest.ini`. Marker
conventions are in [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md#testing-guidelines).

### Code Quality

```bash
pre-commit run --all-files   # ruff (--fix), isort (black profile), black, markdownlint
make lint-md                 # markdownlint only
make lint-dockerfiles        # hadolint on the chatbot Dockerfiles
make lint-nginx              # nginx -t on the generated home and chatbot-frontend configs
make scan-secrets            # Trivy secret scan over the repo
make generate-args           # Regenerate gis-pipeline/docs/ARGS.md from the CLI parser
make i18n-check              # Catalogs cover the source, no dynamic msgids
```

### Dependencies

Each service pins its own `requirements-<service>.txt` and
`requirements-<service>-test.txt`; there is no shared root requirements file.
Update automation lives in `.github/dependabot.yml` and `.github/workflows/`. The
chatbot is never forked — see
[chatbot/docs/ARCHITECTURE.md](chatbot/docs/ARCHITECTURE.md).

## Architecture

- Services talk to each other over the `eoapi-network` Compose network using
  **service names** (`database`, `stac-api`, …) and the internal ports listed in
  [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#services), never host ports.
- The `home` nginx is the single entry point for all frontends — proxy routes,
  nav injection and the chatbot ↔ map `postMessage` bridge are documented in
  [frontend/home/README.md](frontend/home/README.md).

Configuration lives in `.env` (template: `.env.example`; CI values: `.env.ci`).
Three contracts matter more than the rest:

- **Public origin** — STAC asset hrefs are built from `HOST_PROTOCOL://HOST_URL`,
  never from container-local paths (process-api `processes/asset_url_utils.py`,
  gis-pipeline `core/config.py`); see
  [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#stac-asset-hrefs).
  `FORWARDED_ALLOW_IPS` must stay set or uvicorn services advertise `http://`
  behind the HTTPS proxy.
- **Database credentials** — backends use the least-privileged `DB_USER` role,
  never the superuser; see
  [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md#database-credential-model).
- **The `/cog` route** is duplicated in four files with no shared package;
  `make test-repo-consistency` guards them against drift.

### Structure

```text
agri_i18n/        Shared gettext package (catalogs, middleware, CI check)
caddy/            Caddyfile, rate-limit test config
chatbot/          Upstream overrides + tests (never a fork)
data/             input/, output/raster_cog/, duckdb/ — gitignored payloads
docs/             ARCHITECTURE, DEPLOYMENT, I18N, data catalog and guides
frontend/home/    Nginx entry point + Leaflet map page
gis-pipeline/     Ingestion CLI (src/ layout)
process-api/      PyGeoAPI processes/ and config/
raster-api/       TiTiler wiring (src/)
scripts/          DB role creation, spatial index builds, restore helpers
stac-api/         stac-fastapi wiring (src/)
vector-api/       TiPg + DuckDB routers (src/)
```

Each Python service has `Dockerfile.<service>`, `requirements-<service>.txt`,
`requirements-<service>-test.txt`, `pytest.ini`, `test/`, `README.md`,
`CLAUDE.md`, and a `docs/` folder when it needs more than the README. `pytest.ini`
sets `pythonpath` in gis-pipeline (`src`), vector-api (`vector_api`) and
process-api (`processes`); the others import from the package directory directly.

Service boundaries are hard:

- **No service imports another service's Python code.** `agri_i18n` is the only
  shared package (used by `process-api`, `vector-api` and `chatbot`); `scripts/`
  is operator tooling run standalone, not a library to import from.
- Reuse across services happens over HTTP, through the internal service URLs
  already wired in `docker-compose.yml` — not by reaching into a sibling
  directory. "Reuse existing utilities" in [Key Patterns](#key-patterns-to-follow)
  means within the service, or in `agri_i18n`.
- Duplication that must stay in sync across services gets a consistency test
  instead of a shared import — see `make test-repo-consistency` for the `/cog`
  route.

## Internationalization

Backend messages are translated with gettext through `agri_i18n`. The full
contract — msgid rules, locale resolution, scope and the authoring loop — is in
[docs/I18N.md](docs/I18N.md); read it before adding or changing a user-facing
message. Never use f-strings inside `_()`, and keep all logs in English.

## Key Patterns to Follow

- Keep changes minimal and scoped.
- Reuse existing utilities and patterns instead of adding parallel ones.
- Always update or add tests when modifying logic — unit tests for pure logic,
  integration tests for API endpoints, mocked tests when external services are
  involved.
- Use f-strings for formatting (except log calls and gettext msgids).
- Use `is not`, never `not ... is`.
- No inline comments unless the logic is genuinely non-obvious — meaning a reader
  would otherwise delete or break the code. If you cannot name the specific thing
  that goes wrong without the comment, delete the comment. Code should be
  self-explanatory through naming.
- All imports MUST be at the top level of the file.
- Tests are plain pytest: write module-level `def test_*` functions, and group
  related tests in a `class Test*` (no `__init__`) only when they share fixtures
  or setup. Never subclass `unittest.TestCase`.

General Python style (PEP 8, 88-char lines, docstrings) is in
[docs/CONTRIBUTING.md](docs/CONTRIBUTING.md#code-style) and enforced by
pre-commit.

## Typing and Type Hints

- Type hints are required on all code — parameters, return values and
  module-level constants where the type is not obvious.
- Use builtin generics (`list[str]`, `dict[str, int]`) and `X | None` rather than
  `typing.List` / `typing.Optional` in new code; add
  `from __future__ import annotations` when a module must stay importable on the
  oldest interpreter it ships on (3.12).
- Annotate collections you build up (`handlers: list[logging.Handler] = []`) so
  the intent survives refactors.
- There is no mypy gate in CI — ruff and the tests are the only automated check,
  so hints must be accurate by review, not by tool.

Python versions differ per service; check the service's `Dockerfile.<service>`
and run code in its own container.

## Logging

- `gis-pipeline` configures structlog in `core/logging_setup.py`; every other
  service uses stdlib logging with a module-level
  `logger = logging.getLogger(__name__)`.
- **Log in English**, always, even when the raised message is translated.
- Use lazy `%s` interpolation, not f-strings:
  `logger.warning("STAC publish failed: %s", exc)`. gis-pipeline overrides this
  with structlog key-values — see
  [gis-pipeline/CLAUDE.md](gis-pipeline/CLAUDE.md#logging).
- Never log secrets, credentials or API keys.

## Security Considerations

- **Only `80`/`443` (Caddy) are public.** Never add a `ports:` mapping to a
  backend service; use `expose:` only.
- Secrets (`LLM_API_KEY`, `OPENEO_REFRESH_TOKEN`, DB passwords) live in `.env`,
  which is gitignored — never commit them, never echo them into logs or tests.
- Containers run with `no-new-privileges:true` and explicit CPU/memory limits;
  keep both on any service you add or change.
- CORS, rate limiting, auth and the pre-deploy checklist are in
  [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md#6-security-checklist).
