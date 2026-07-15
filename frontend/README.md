# frontend

Browser-facing services for Agri-SDSS. Three UIs, all served under a single origin via the `home` nginx reverse proxy.

**Port**: 8084 (home) | **HTTPS**: via Caddy at :443

## Services

| Service | Path | Description |
| --- | --- | --- |
| `home` | `/` | Leaflet map page, nginx reverse proxy for all frontends and APIs |
| `stac-browser` | `/stac/` | STAC catalog explorer (Vue.js, official radiantearth/stac-browser image) |
| `mos-chatbot-frontend` | `/chatbot/` | AI assistant UI (Vite/React, served by nginx) |

## Start

```bash
docker compose up -d home stac-browser mos-chatbot-frontend
```

## What it does

- `home` proxies `/stac/` → stac-browser, `/chatbot/` → mos-chatbot-frontend, `/api/` and `/chat/` → mos-chatbot-backend
- The Leaflet map communicates with the chatbot via `postMessage` (see `chatbot-bridge.js`)
- STAC Browser auto-connects to the STAC API and renders collection/item pages with map footprints

## Docs

→ [Tile caching](docs/tiles_generation_cache.md)  
→ [GeoParquet in Leaflet](docs/read_geoparquet_with_leaflet.md)  
