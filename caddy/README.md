# caddy

Public entry point for the Agri-SDSS platform. Handles TLS termination, HTTP→HTTPS redirect, and rate limiting on OGC process routes.

**Port**: 443 (HTTPS) / 80 (redirect) | **Requires**: `home` frontend service running as upstream

## Start

```bash
docker compose up -d caddy
```

## What it does

- Terminates TLS — self-signed (`tls internal`) by default for `localhost`; point a real domain at the server and remove `tls internal` for automatic Let's Encrypt
- Proxies all traffic to the `home` service, which routes to individual APIs
- Rate-limits OGC process execution: 10 req/min per IP on `POST /process-api/processes/*/execution`
- Rate-limits the chatbot per IP: 10 req/min on the LLM agent loop (`POST /api/query`,
  `/api/process-comparison-query`, `/api/geoint/*`, `/sdss/*`), 30 req/min on catalogue
  searches, 60 req/min on `GET /api/*`. These zones are the chatbot's only working
  per-IP limit — the backend's own limiter keys on `request.client.host`, which behind
  this proxy is always the `home` container IP, so it degrades to one shared bucket
- Rate-limits public COG downloads: 30 req/min per IP on `GET /cog/*`, which serves
  raster files (up to 2.49 GB) with no auth. Ranged reads from GDAL's `/vsicurl`
  stay well under that; the zone exists to bound a client that pulls whole
  multi-gigabyte files in a loop
- Sets security headers: HSTS, `X-Frame-Options`, `X-Content-Type-Options`, CSP

## Configuration

`Caddyfile` — production config  
`Caddyfile.test` — shorter rate-limit windows for integration tests

## Docs

→ [Deployment guide](../docs/DEPLOYMENT.md)
