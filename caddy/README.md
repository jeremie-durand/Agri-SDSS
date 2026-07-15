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
- Rate-limits OGC process execution: 10 req/min per IP on `POST /mos-pygeoapi/processes/*/execution`
- Sets security headers: HSTS, `X-Frame-Options`, `X-Content-Type-Options`, CSP

## Configuration

`Caddyfile` — production config  
`Caddyfile.test` — shorter rate-limit windows for integration tests

## Docs

→ [Deployment guide](../docs/DEPLOYMENT.md)
