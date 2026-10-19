# CLAUDE.md — caddy

Service guide for `caddy`. It specializes the [root CLAUDE.md](../CLAUDE.md)
and wins wherever the two differ; everything the root file says still applies
unless overridden here.

## Service Overview

The platform's only public entry point, and the **only** service with a
`ports:` mapping (`80`, `443`). It does four things, then proxies everything to
`home:8080`:

1. **TLS.** A self-signed certificate (`tls internal`) by default, or Let's
   Encrypt when `ACME_EMAIL` is set.
2. **HTTP → HTTPS** redirect on `:80`.
3. **Per-IP rate limiting** (the `caddy-ratelimit` plugin). It answers
   `429` + `Retry-After`.
4. **Security headers**, CSP included, for every response.

Routing to individual services is home nginx's job
([frontend/home/CLAUDE.md](../frontend/home/CLAUDE.md)), not Caddy's.

- Overview: [README.md](README.md). Deployment and TLS:
  [docs/DEPLOYMENT.md](../docs/DEPLOYMENT.md#3-tls--caddy). Where they
  disagree with the `Caddyfile`, trust the `Caddyfile`, and fix the doc when
  you touch that area.

## Common Commands

Run from the repo root.

```bash
docker compose restart caddy        # After editing Caddyfile (bind-mounted read-only)
docker compose exec caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
docker compose up -d --build caddy  # Only after changing Dockerfile.caddy (plugin build)
make test-caddy                     # Rate-limit integration tests (see Testing)
docker compose logs -f caddy
```

## Structure

```text
Caddyfile           Production config — bind-mounted at /etc/caddy/Caddyfile
Caddyfile.test      Same zones with 5 s windows, for make test-caddy only
Dockerfile.caddy    xcaddy build adding github.com/mholt/caddy-ratelimit
test/               pytest suite run from a throwaway python container
```

The image only adds the plugin. Configuration is never baked in, so editing
the `Caddyfile` needs a restart, not a rebuild.

## Configuration

- **Site and TLS come from env, not from editing the file.**
  `{$SITE_ADDRESS:localhost, agri-sdss.local}` and `tls {$ACME_EMAIL:internal}`
  read `SITE_ADDRESS` / `ACME_EMAIL`, which compose passes with the same
  defaults. For production, set `SITE_ADDRESS=<domain>` and
  `ACME_EMAIL=<email>` in `.env`, plus `HOST_PROTOCOL=https` and
  `HOST_URL=<domain>` for the rest of the platform. Apply with
  `docker compose up -d`: a plain `restart` keeps the old environment.
- **Rate limits are hard-coded** in the `Caddyfile`. No env var changes them.
  To tune a zone, edit its `window`/`events`, mirror the change in
  `Caddyfile.test` if the zone's matcher changes, then restart.
- `caddy_data` holds the certificates and ACME account. Never delete it, or
  Let's Encrypt rate limits can lock the domain out.
- Global `servers.timeouts` bound only how long a client may take to send its
  request (`read_header` 10 s, `read_body` 30 s, `idle` 2 min). There is
  deliberately **no write timeout**, because chat turns and process runs
  stream for up to 10 min (home: 600 s / 630 s).

## Rate-Limit Zones

| Zone | Match | Limit / IP |
| --- | --- | --- |
| `pygeoapi_exec` | `POST /process-api/processes/*/execution` | 10 / min |
| `pygeoapi_browse` | `GET /process-api/*` | 60 / min |
| `chatbot_llm` | `POST /api/query`, `/api/process-comparison-query`, `/api/geoint/*`, `/sdss/*` | 10 / min |
| `chatbot_search` | `POST /api/stac-search`, `/api/veda-search`, `/api/structured-search`, `/api/sign-mosaic-url`, `/api/session-reset` | 30 / min |
| `chatbot_browse` | `GET /api/*` | 60 / min |
| `cog_download` | `GET /cog/*` | 30 / min |

- Zones split by method so a request is counted in one zone only. Keep new
  zones method-scoped the same way.
- `key {remote_host}` is the TCP peer. That is correct only while Caddy is the
  edge. Behind a load balancer or CDN, every visitor would share one bucket
  until you configure `trusted_proxies` and key on the client IP.
- These zones are the chatbot's **only** real per-IP limit: the backend's own
  limiter sees the `home` container IP.
- `cog_download` bounds request count, not bytes. The byte cap is
  `limit_rate` in the home nginx `/cog` location.
- `/stac-api`, `/vector-api` and `/raster-api` have no zone. `/stac-api` writes
  are refused by home nginx instead (see
  [stac-api/CLAUDE.md](../stac-api/CLAUDE.md#security)).
- The chatbot path lists name upstream chatbot routes. Re-check them after a
  `CHATBOT_VERSION` bump.

## Security Headers

- HSTS (1 year, `includeSubDomains`), `X-Frame-Options SAMEORIGIN`,
  `nosniff`, `Referrer-Policy`, and the `Server` header removed.
- **CSP** allows scripts only from `'self'`, unpkg, cdnjs and jsdelivr, and
  `connect-src` only `'self'` plus Planetary Computer. A new CDN library or a
  new browser-side API origin in any UI must be added here, or the browser
  blocks it silently. Caddy's headers apply on top of the chatbot nginx's own
  headers.

## Testing

`make test-caddy` works against the **running** stack:

1. It copies `Caddyfile.test` into the container and hot-reloads Caddy with it.
2. It runs `caddy/test/` from a `python:3.12-slim` container on
   `eoapi-network` against `https://caddy`.
3. It reloads the production `Caddyfile`.

- Step 3 runs even when tests fail, and the target still exits non-zero. If
  `make` is interrupted (Ctrl-C) mid-run, Caddy is left on the test config
  (5 s windows, **no security headers**). Restore it with
  `docker compose restart caddy`.
- It is not part of `make test-all` or CI. Run it by hand after changing
  zones.
- `Caddyfile.test` must keep the same zone names and matchers as the
  production file. Nothing checks that automatically.
- The `RATE_LIMIT_*` variables the Makefile passes only tell the tests the
  limits `Caddyfile.test` sets. They configure nothing.
