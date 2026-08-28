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
├── backend/
│   ├── tools_registry.py          # replaces upstream; exports SDSS_TOOLS
│   └── tools/
│       ├── land_use_analyzer.py   # STAC items + parcel GeoJSON → LandUseHistory
│       ├── som_predictor.py       # raster-api SOM response → SomPrediction
│       └── quebec_zones.py        # region name → bounding box
└── frontend/
    ├── nginx.conf                 # proxies /api/* → backend:8000
    └── src/components/
        ├── SoilMapViewer.tsx      # SOM tile layer; postMessages bbox to parent map
        ├── ParcelSelector.tsx     # parcel ID input for Quebec workflows
        └── QuebecToolbar.tsx      # quick-action prompts for SDSS workflows
```

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

## Upstream upgrade process

A daily GitHub Actions workflow ([`chatbot-release-watcher.yml`](../../.github/workflows/chatbot-release-watcher.yml)) monitors `OpenGeo-AI-Assistant` releases and auto-opens a PR bumping `CHATBOT_VERSION` in `.env.example`.

Before merging:

1. CI security scan passes (CVE, secrets, Hadolint)
2. `verify-overrides` job confirms override paths are still valid
3. Tested locally with `make build-safe`
4. All chatbot tools resolve correctly against internal APIs
5. Quebec UI components render as expected

To upgrade manually: update `CHATBOT_VERSION` in `.env`, then rebuild.

Development guidelines and test commands are in [CLAUDE.md](../CLAUDE.md).
