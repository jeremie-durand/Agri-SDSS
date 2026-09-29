# CLAUDE.md — chatbot

Service guide for `chatbot`. It specializes the [root CLAUDE.md](../CLAUDE.md)
and wins wherever the two differ; everything the root file says still applies
unless overridden here.

## Service Overview

Agri-SDSS assistant built on
[OpenGeo-AI-Assistant](https://github.com/jeremie-durand/OpenGeo-AI-Assistant)
(our own upstream). Two containers:

- `chatbot-backend` — FastAPI + LLM agent, Python 3.12, port 8000.
- `chatbot-frontend` — Vite/React SPA served by nginx, port 3001.

Both use `expose:` only; users reach the UI through Caddy → `home` at
`/chatbot/`.

- Override layout, language contract, greeting override, upgrade checklist:
  [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Where it disagrees with the
  code or `docker-compose.yml`, trust those, and fix the doc when you touch
  that area.
- Map ↔ chatbot `postMessage` bridge (`AGRI_SDSS_*`): owned by `home` —
  [frontend/home/README.md](../frontend/home/README.md).

## The Override Rule

The chatbot is **never forked**. Both Dockerfiles clone upstream at
`CHATBOT_VERSION`, then `COPY chatbot/overrides/` on top: a same-path file
replaces upstream, a new path is additive.

- **Backend overrides are all additive.** No file in `overrides/backend/`
  shadows an upstream path. Keep it that way — never add a same-name copy of an
  upstream module (e.g. `fastapi_app.py`, `geoint/router_agent.py`).
- `overrides/frontend/nginx.conf` is the only file that replaces upstream.
- Change upstream behaviour without shadowing it:
  - wrap it at startup, as `sdss_main.py` does (mounts `/sdss`, adds
    `LocaleASGIMiddleware`, hoists CORS outside the API-key middleware);
  - patch data at import, as `sitecustomize.py` does (MODIS NDVI rescale);
  - route Agri-SDSS–specific flows through `/sdss/*` instead of upstream's
    router agent;
  - fix generic bugs upstream and bump `CHATBOT_VERSION`.
- One patch lives in `Dockerfile.chatbot-backend`, not `overrides/`: a `sed`
  rewrite of `datetime.utcnow()` in upstream `fastapi_app.py`. Check it still
  matches after an upgrade; `sed` fails silently.
- Before relying on an upstream name, check it at the pinned tag (`git show
  <tag>:opengeo-ai-assistant/container-app/<file>`), not upstream `main`.

`CHATBOT_VERSION` is pinned in four files (`.env.example`, `docker-compose.yml`,
both Dockerfiles) plus your untracked `.env`; bump them together. The
release-watcher PR and the upgrade checklist are in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#upstream-upgrade-process).

## Common Commands

Run from the repo root.

```bash
make test-chatbot          # Rebuilds chatbot-backend (test target), runs the suite
make lint-dockerfiles      # hadolint on both Dockerfiles
make lint-nginx            # nginx -t on overrides/frontend/nginx.conf

# Single test — tests and overrides are baked into the image, so rebuild first
docker compose build chatbot-backend
docker compose run --rm chatbot-backend pytest chatbot/test/test_sdss_api.py -v

# Apply an override change to the running stack
docker compose up -d --build chatbot-backend    # or chatbot-frontend
```

Nothing is bind-mounted: every change to `overrides/`, `test/` or
`agri_i18n` needs a rebuild. CI builds with `INCLUDE_OLLAMA=stub` to skip the
Ollama bundle.

## Structure

```text
Dockerfile.chatbot-backend   i18n catalogs → Ollama (full|stub) → clone → runtime → test
Dockerfile.chatbot-frontend  clone → npm build with overrides/frontend → nginx
overrides/backend/           Copied to /app (upstream container-app/ root)
  entrypoint.sh              Starts Ollama only if LLM_BASE_URL is :11434; runs uvicorn
  sdss_main.py               uvicorn target (sdss_main:app) — wraps upstream app
  sdss_api.py                POST /sdss/query: OpenAI-compatible tool-calling loop
  tools_registry.py          process-api tool functions + unimplemented stubs
  sitecustomize.py           Import-time patch of upstream render configs
  tools/                     Pure helpers (region bbox, land-use, SOM wrapper)
overrides/frontend/nginx.conf  Replaces upstream nginx.conf
test/                        Copied to /app/chatbot/test in the test image
```

## Backend Behaviour

- `/sdss/query` bypasses upstream's router agent entirely. It pre-fetches the
  process-api catalog and schemas into the system prompt, then runs up to 6
  tool-calling rounds against `LLM_BASE_URL` with the `openai` client — whatever
  `LLM_PROVIDER` says, the endpoint must be OpenAI-compatible.
- Tool calls that Llama/Ollama returns as JSON text are recovered by
  `_extract_text_tool_call()`; keep that fallback when changing the loop.
- `_TOOL_DEFS` and `_TOOL_FNS` in `sdss_api.py` are what the LLM sees. Adding a
  tool means a function in `tools_registry.py` **and** entries in both.
  `SDSS_TOOLS` is not consumed by upstream at this tag.
- The `tools/` helpers and the four `NotImplementedError` stubs in
  `tools_registry.py` are not wired into any tool yet; do not assume they run.
- Every server-side call to process-api forwards the request locale via
  `_locale_headers()`; new internal calls must do the same.

## Service Wiring

- Internal URLs come from env vars set in `docker-compose.yml`
  (`STAC_API_URL`, `RASTER_API_INTERNAL_URL`, `VECTOR_API_INTERNAL_URL`,
  `VECTOR_API_URL`, `PYGEOAPI_INTERNAL_URL`). Read them with `os.environ`;
  never hard-code a host or port in an override.
- Ports must match each target's `expose:` (stac-api 8081, raster-api 8082,
  vector-api 8083, process-api 5000). `test/conftest.py` sets its own values,
  so tests do not catch a wrong compose URL.
- `nginx.conf` proxies only `/api/*`, `/sdss/*` and three root JSON documents,
  with a 600 s read timeout for LLM loops. `home` nginx mirrors these blocks —
  change both together.
- `FORWARDED_ALLOW_IPS` must stay set: the rate limiter buckets on the client
  IP resolved from `X-Forwarded-For` (`test/test_proxy_headers.py` guards it).

## Internationalization

- Only `agri_i18n/__init__.py` and `middleware.py` are copied into the image;
  the `.mo` catalogs are compiled in the Dockerfile's `i18n` stage.
- `LocaleASGIMiddleware` negotiates `Accept-Language` for every route.
  `/sdss/query` overrides it with `set_locale(req.language)` from the body.
- Translate validation/auth errors and user-visible fallbacks with `_()`.
  Server misconfiguration (e.g. missing `LLM_API_KEY`) stays English.
- UI language comes from upstream `I18nContext` reading `sdss-lang` — see
  [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#language-fren). Do not add a
  second mechanism.

## Security

- `/sdss/*` requires `X-API-Key` when `ENABLE_AUTH=true`; keep
  `Depends(_verify_api_key)` on every new `/sdss` route.
- Never log `LLM_API_KEY`, `API_KEY`, or full LLM payloads that may contain
  them.
- Keep the security headers and `limit_conn` in `nginx.conf` when editing it.

## Testing

- Tests import override modules as top-level (`from sdss_api import …`),
  because overrides land at `/app` and `PYTHONPATH=/app`.
- `asyncio_mode = auto` — async tests need no decorator.
- Mark every test `@pytest.mark.unit` (pure logic) or `@pytest.mark.mocked`
  (HTTP or LLM replaced with `unittest.mock`/`monkeypatch`). No test may reach
  a live service or a real LLM.
- New `/sdss` routes need auth-on/auth-off tests; new user-facing messages need
  a French-default and an English test (see `test_sdss_api.py`).
- `test_proxy_headers.py` asserts uvicorn behaviour pinned by upstream's
  `requirements.txt` — run it after every `CHATBOT_VERSION` bump.
