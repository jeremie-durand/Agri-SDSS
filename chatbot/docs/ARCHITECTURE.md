# chatbot — Architecture

## Overview

`chatbot` layers Agri-SDSS–specific overrides on top of [OpenGeo-AI-Assistant](https://github.com/jeremie-durand/OpenGeo-AI-Assistant). The upstream chatbot is not forked — it is cloned at Docker build time and the override files replace or extend it.

## Containers

| Service | Port (host) | Port (container) | Role |
| --- | --- | --- | --- |
| `chatbot-backend` | `CHATBOT_BACKEND_PORT` (8005) | 8000 | FastAPI + LLM agent |
| `chatbot-frontend` | `CHATBOT_FRONTEND_PORT` (3001) | 80 | Vite/React SPA served by nginx |

## Build-time override pattern

```text
upstream source (cloned at CHATBOT_VERSION)
         │
         ▼
   [upstream code copied into image]
         │
         ▼
chatbot/overrides/   ← layered on top (COPY runs after)
```

Files in `overrides/` with the same relative path as an upstream file **replace** it. New files are additive.

## Override layout

```text
overrides/
├── backend/                       # all additive — no upstream counterpart
│   ├── entrypoint.sh              # starts local Ollama only when LLM_BASE_URL targets :11434
│   ├── sdss_main.py               # uvicorn entry point; mounts the SDSS router + locale middleware
│   ├── sdss_api.py                # /sdss/* router for OGC API - Processes queries
│   ├── sitecustomize.py           # auto-imported at startup; fixes the MODIS NDVI rescale range
│   ├── tools_registry.py          # exports SDSS_TOOLS for the upstream agent kernel
│   └── tools/
│       ├── __init__.py            # re-exports the tool helpers
│       ├── land_use_analyzer.py   # STAC items + parcel GeoJSON → LandUseHistory
│       ├── quebec_zones.py        # region name → bounding box
│       └── som_predictor.py       # raster-api SOM response → SomPrediction
└── frontend/
    └── nginx.conf                 # replaces upstream; proxies /api/* → backend:8000
```

Every backend override is **additive** — none shadows an upstream path, so upstream
refactors cannot silently change their behaviour. `nginx.conf` is the only file that
replaces an upstream counterpart, and so the only one to diff on an upgrade.

`vite.config.ts` used to sit here too, carrying the Vite 8 / Rolldown build fixes. Those
were upstreamed in `v0.2.1-alpha`, which also strips `console` output from production
bundles, so the override was deleted rather than kept in sync.

## Internal service wiring

The backend reaches other Agri-SDSS services over the Docker Compose network:

| Env var | Docker URL |
| --- | --- |
| `STAC_API_URL` | `http://stac-api:8080` |
| `RASTER_API_INTERNAL_URL` | `http://raster-api:8080` |
| `VECTOR_API_INTERNAL_URL` | `http://vector-api:8080` |
| `PYGEOAPI_INTERNAL_URL` | `http://process-api:5000` |

## SDSS tools

`tools_registry.py` exports `SDSS_TOOLS`, the set of tools injected into the upstream LLM agent kernel:

| Tool | Description |
| --- | --- |
| `list_pygeoapi_processes` | Discover available OGC processes on process-api |
| `get_process_schema` | Fetch input/output schema for one process |
| `execute_pygeoapi_process` | Execute a process with given inputs |

Domain-specific stubs (`predict_soil_organic_matter`, `query_agricultural_parcels`, `search_soil_datasets`, `run_som_process`) exist in the same file but are not yet exported.

## Key data sources

- **Agricultural parcels** — Vector API parquet collection `bdppad_v03_an_2023_s_20250120`
- **Soil datasets** — STAC collections `sentinel2_eo_products`, `lidar_quebec`, `demo_collection`

## Map integration

`SoilMapViewer.tsx` uses `window.parent.postMessage` with `type: 'AGRI_SDSS_ZOOM'` to sync the parent Leaflet map when embedded in an iframe. The map page listens for both `AGRI_SDSS_ZOOM` and `AGRI_SDSS_TILES` messages (see `frontend/home/html/js/chatbot-bridge.js`).

## LLM configuration

The backend is provider-agnostic via the upstream framework:

| Variable | Default | Description |
| --- | --- | --- |
| `LLM_PROVIDER` | `openai` | Provider name |
| `LLM_API_KEY` | — | API key |
| `LLM_MODEL` | — | Model identifier |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | Override for local models |
| `LLM_MAX_TOKENS` | `1000` | Max tokens per response |

## Language (FR/EN)

Language is shared between `home` and the chatbot through `localStorage` — which works
only because every sub-application is proxied through the single `home` origin.

| Step | Who | What |
| --- | --- | --- |
| 1 | `nav-inject.js` (home) | writes `localStorage['sdss-lang']` (`fr` \| `en`) and dispatches an `sdss-lang-change` CustomEvent on `window` |
| 2 | upstream `i18n/I18nContext.tsx` | reads the same key on mount, then listens for `sdss-lang-change` (same tab) and `storage` (other tabs) |
| 3 | `chatbot-bridge.js` | maps the key to an `Accept-Language` header on its own API calls |
| 4 | `LocaleASGIMiddleware` (`sdss_main.py`) | binds the request locale so backend messages come back translated |

Upstream's `I18nContext` is written against this contract on purpose (it names
`sdss-lang` and `sdss-lang-change` directly), so the chatbot UI follows the home nav
toggle with no extra wiring on our side. Do not add a second language mechanism.

**Greeting override:** the chat greeting is the one string we deliberately override.
Upstream owns and translates it (`chat.welcome`), but its wording is generic
("OpenGeo AI Assistant"); `chatbot-bridge.js` rewrites it after render so the user sees
Agri-SDSS branding and the Québec framing in both languages.

This is a permanent override, not a workaround — keep it across upgrades. It matches
upstream's greeting *and* its own output, so it stays correct whether upstream fixes the
greeting at mount (older builds) or re-translates it on every language switch, and its
`MutationObserver` is loop-safe because it writes nothing once the text already matches.
If upstream ever changes its greeting wording, add the new opening words to `SNIPPETS`.

## Upstream upgrade process

A daily GitHub Actions workflow ([`chatbot-release-watcher.yml`](../../.github/workflows/chatbot-release-watcher.yml)) monitors `OpenGeo-AI-Assistant` releases and auto-opens a PR bumping `CHATBOT_VERSION` in the four pinned files:

- `.env.example`
- `docker-compose.yml`
- `chatbot/Dockerfile.chatbot-backend`
- `chatbot/Dockerfile.chatbot-frontend`

`.env.ci` does not pin the version — CI inherits the `docker-compose.yml` default. Your
local `.env` is untracked, so bump it by hand as well.

Before merging:

1. CI security scan passes (CVE, secrets)
2. `verify-overrides` job lists each override against the new tag — note that it is
   **informational only** and never fails the build; read its output
3. `docker compose build chatbot-backend` succeeds
4. `make test-chatbot` passes
5. All chatbot tools resolve correctly against internal APIs

To upgrade manually: bump `CHATBOT_VERSION` in the four files above plus `.env`, then
rebuild. Diff the upstream counterpart of `nginx.conf`, the only file an override
replaces, to catch interface drift.

Development guidelines and test commands are in [CLAUDE.md](../CLAUDE.md).
