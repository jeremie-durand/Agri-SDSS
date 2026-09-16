# API Quick Reference

Quick access guide to all service endpoints. For detailed documentation, refer to each service's README.

Every service is reached through the single public origin — Caddy on `443`, which proxies to
the `home` nginx. The per-service ports below are container-internal and are **not** published
to the host, so `http://<host>:8081` will not connect. Replace `<host>` with your domain; add
`-k` when testing against a local deployment with a self-signed certificate.

## Service URLs

| Service | Public path | Internal port | Documentation |
| --- | --- | --- | --- |
| **STAC API** | `https://<host>/stac-api/` | 8081 | [stac-api/README.md](../../stac-api/README.md) |
| **Raster API** | `https://<host>/raster-api/` | 8082 | [raster-api/README.md](../../raster-api/README.md) |
| **Vector API** | `https://<host>/vector-api/` | 8083 | [vector-api/README.md](../../vector-api/README.md) |
| **Process API** | `https://<host>/process-api/` | 5000 | [process-api/README.md](../../process-api/README.md) |
| **STAC Browser** | `https://<host>/stac/` | 8080 | [frontend/stac-browser/README.md](../../frontend/stac-browser/README.md) |

## Quick Examples

### STAC API

```bash
# List collections
curl https://<host>/stac-api/collections

# Search items
curl -X POST https://<host>/stac-api/search \
  -H "Content-Type: application/json" \
  -d '{"collections": ["my-collection"]}'

# API documentation (browser)
https://<host>/stac-api/api.html
```

### Raster API

```bash
# List available COGs
curl https://<host>/raster-api/collections

# Inspect one COG
curl "https://<host>/raster-api/cog/info?url=file:///data/<name>.tif"

# Get a tile — note the tile matrix set segment, which is required
curl "https://<host>/raster-api/cog/tiles/WebMercatorQuad/12/1235/1464.png?url=file:///data/<name>.tif&bidx=1"
```

### Vector API

```bash
# PostGIS-backed collections
curl https://<host>/vector-api/postgis/collections
curl https://<host>/vector-api/postgis/collections/{collectionId}/items?limit=10

# GeoParquet-backed collections
curl https://<host>/vector-api/parquet/collections
```

### Process API

```bash
# List processes
curl https://<host>/process-api/processes

# Get process details
curl https://<host>/process-api/processes/{processId}
```

## Environment

All services are configured via `docker-compose.yml`. Check service READMEs for:

- Configuration options
- Environment variables
- Required databases (PostGIS, DuckDB)
- Data directories

See [CONTRIBUTING.md](../CONTRIBUTING.md) for deployment setup.
