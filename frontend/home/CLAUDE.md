# CLAUDE.md — frontend/home

Service guide for `home`. It specializes the [root CLAUDE.md](../../CLAUDE.md)
and wins wherever the two differ; everything the root file says still applies
unless overridden here.

## Service Overview

`nginx:alpine` on port 8080 (`expose:` only; Caddy is the only way in). It has
three jobs:

1. **Static site:** the Leaflet map (`/` → `map.html`), `/services`
   (`index.html`), `/data`, `/about` and `/report-bug`. Vanilla JS, ES modules,
   no build step.
2. **Single-origin reverse proxy** for every other UI and API. Proxy table,
   request flow and module list: [README.md](README.md). Where the README
   disagrees with `scripts/entrypoint.sh`, trust the script, and fix the
   README when you touch that area.
3. **Glue injected into other apps** with `sub_filter`: the shared nav
   (`/sdss-nav.js`) in STAC Browser and the chatbot, and `chatbot-bridge.js` in
   the chatbot.

No Python here, so the root Python, typing and i18n rules do not apply. The
shared rules that still bind: no `ports:` mapping, service names on
`eoapi-network`, and the `/cog` route contract.

## Common Commands

Run from the repo root.

```bash
make lint-nginx               # Renders entrypoint.sh's config and runs nginx -t
make test-repo-consistency    # /cog route guard (reads entrypoint.sh + compose)

docker compose up -d --build home            # After editing entrypoint.sh or index.html
docker compose up -d --force-recreate home   # After changing only env vars
docker compose exec home cat /etc/nginx/conf.d/default.conf   # Generated config

# home has no host port — probe from inside the network
docker run --rm --network eoapi-network curlimages/curl:latest -sI http://home:8080/
```

What needs a rebuild:

| Changed | Action |
| --- | --- |
| `html/js/*`, `html/css/*`, `map.html`, `data.html`, `about.html`, `report-bug.html` | Nothing. They are bind-mounted read-only; hard-refresh the browser. |
| `html/index.html` | Rebuild. It is baked in as `index.html.template`. |
| `scripts/entrypoint.sh` (nginx config) | Rebuild, then `make lint-nginx`. |
| `PRIMARY_COLLECTION_PREFIX`, `MAP_*` env | `--force-recreate` (written to `/runtime-config.js` at start). |

## The Nginx Config

- The whole server block is a single-quoted heredoc in `scripts/entrypoint.sh`,
  so `$host`, `$remote_addr` and the like stay nginx variables. Shell values
  cannot be expanded inside it. Ports are patched afterwards with `sed`, which
  rewrites the placeholder `http://<svc>:8080/`. Only stac-api, vector-api and
  raster-api are patched. The stac-browser (8080), chatbot (3001/8000) and
  process-api (5000) targets are literal. Changing one of those means editing
  the script. Compose still passes `STAC_BROWSER_PORT`, `PROCESS_API_PORT`,
  `HOST_PROTOCOL` and `HOST_URL` to `home`, but nothing reads them.
- **Upstream IPs are resolved once, at startup.** `proxy_pass` uses literal
  hostnames, so `resolver 127.0.0.11 valid=5s` never applies. Recreating any
  proxied container therefore needs `docker compose restart home` (see the
  root Ops note). Moving to variable-based `proxy_pass` would fix it, but it
  changes how the URI is forwarded, so every location would need rewriting.
- `/stac-api/` is **read-only**: `limit_except GET OPTIONS`, with a separate
  exact `location = /stac-api/search` that also allows `POST`. Do not loosen
  it; add an exact-match location for any new read-only `POST`. See
  [stac-api/CLAUDE.md](../../stac-api/CLAUDE.md#security).
- The chatbot backend is proxied only for `/api/*`, `/sdss/*` and three root
  JSON documents. `chatbot/overrides/frontend/nginx.conf` mirrors these blocks
  and their timeouts, so change both together.
- Timeouts are sized to the backends: `/api` and `/sdss` 600 s (LLM tool
  loops), `/process-api/` 630 s (gunicorn 600 s + margin), `/vector-api/`
  120 s.
- `/cog/<file>.tif` is served statically from `./data/output/raster_cog`,
  mounted at `/usr/share/nginx/cog`. The regex admits only `.tif`/`.tiff`, and
  the location is rate-limited. The route string and the mount are one of the
  four `/cog` copies, so run `make test-repo-consistency` after touching
  either.
- `sub_filter` needs uncompressed upstream bodies. Keep
  `proxy_set_header Accept-Encoding ""` on every location that uses it.
- Security headers and CSP come from Caddy. A new CDN script must be allowed
  in `caddy/Caddyfile`'s CSP, which currently lists unpkg, cdnjs and jsdelivr.

## Front-End Code

- Map entry point: `map.html` loads the vendored and CDN libraries, then
  `/runtime-config.js`, then `js/app.js` as a module. `config.js` merges
  `window.AGRI_CONFIG` over its defaults, and `state.js` holds the shared
  map instance and API bases.
- Call backends only through the same-origin proxy paths (`/vector-api/`,
  `/raster-api/`, `/stac-api/`, `/process-api/`, `/aac-identify/`). Never use a
  service host or port.
- `chart.umd.min.js` and `turf.min.js` are vendored minified builds. Replace
  them wholesale; never edit them.
- `catalog.js` is dead code (nothing imports it). `data-catalog.js` drives
  `/data` from `catalog.json` plus the live collection lists.
- `leaflet-offline-sw.js` caches only `/raster-api/` tiles. Keep other APIs out
  of its cache.
- `somRasterBasenames` in `config.js` must match the SIIGSOL COG file names
  gis-pipeline produces.

## Language (FR/EN)

- The UI language is `localStorage['sdss-lang']` (`fr` default, or `en`).
  `nav-inject.js` writes it and dispatches `sdss-lang-change` on `window`.
- Each page and script carries its own small `{en, fr}` dictionary and reads
  that key. There is no shared i18n library. Add both languages for every new
  string, and listen for `sdss-lang-change` if the text is visible while the
  toggle is used.
- The chatbot UI follows the same key through upstream `I18nContext`, and
  `chatbot-bridge.js` rewrites the greeting. See
  [chatbot/docs/ARCHITECTURE.md](../../chatbot/docs/ARCHITECTURE.md#language-fren).
  Do not add a second mechanism.

## Chatbot ↔ Map Bridge

- `chatbot-bridge.js` runs **inside the chatbot iframe** (injected into
  `<head>`). It receives `AGRI_SDSS_CONTEXT` from the map and posts
  `AGRI_SDSS_ZOOM` / `AGRI_SDSS_TILES` to `window.parent`.
- It depends on the chatbot's DOM and Axios responses, so re-check it after
  every `CHATBOT_VERSION` bump.
- The `/chatbot/` location hides upstream `X-Frame-Options` and sets
  `SAMEORIGIN` so the map can frame it. Keep both.

## Testing

There is no JS test suite. Verification is:

- `make lint-nginx` for every `entrypoint.sh` change (CI runs it);
- `make test-repo-consistency` when `/cog` or its mount changes;
- a probe of each touched route from inside `eoapi-network` (status codes
  through `http://home:8080/...`);
- a manual check of the map in a browser, in both languages.
