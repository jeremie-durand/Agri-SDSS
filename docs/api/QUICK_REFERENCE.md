# API Quick Reference

Quick access guide to all service endpoints. For detailed documentation, refer to each service's README.

## Service URLs

| Service | Port | Base URL | Documentation |
|---------|------|----------|-----------------|
| **STAC API** | 8081 | http://localhost:8081 | [stac-api/README.md](../../stac-api/README.md) |
| **Raster API** | 8082 | http://localhost:8082 | [raster-api/README.md](../../raster-api/README.md) |
| **Vector API** | 8083 | http://localhost:8083 | [vector-api/README.md](../../vector-api/README.md) |
| **Process API** | 5000 | http://localhost:5000 | [pygeoapi/README.md](../../pygeoapi/README.md) |
| **Frontend** | 8085 | http://localhost:8085 | [frontend/stac-browser/README.md](../../frontend/stac-browser/README.md) |

## Quick Examples

### STAC API
```bash
# List collections
curl http://localhost:8081/collections

# Search items
curl -X POST http://localhost:8081/search \
  -H "Content-Type: application/json" \
  -d '{"collections": ["my-collection"]}'

# API Documentation
http://localhost:8081/api.html
```

### Raster API
```bash
# List available COGs
curl http://localhost:8082/cog/info

# Get tile (PNG)
curl http://localhost:8082/cog/tiles/10/512/512.png?url=<COG_URL>
```

### Vector API
```bash
# List collections
curl http://localhost:8083/collections

# Get features
curl http://localhost:8083/collections/{collectionId}/items
```

### Process API
```bash
# List processes
curl http://localhost:5000/processes

# Get process details
curl http://localhost:5000/processes/{processId}
```

## Environment

All services are configured via `docker-compose.yml`. Check service READMEs for:
- Configuration options
- Environment variables
- Required databases (PostGIS, DuckDB)
- Data directories

See [CONTRIBUTING.md](../CONTRIBUTING.md) for deployment setup.
