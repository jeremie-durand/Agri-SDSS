# raster-api

OGC raster service built on TiTiler. Serves Cloud-Optimized GeoTIFFs (COGs) as map tiles, WCS coverages, WMS layers, and band statistics.

**Port**: 8082 | **Requires**: COG files in `data/output/raster_cog/`

Interactive API docs: `http://<host>/mos-raster/api.html`

## Start

```bash
docker compose up -d raster-api
```

## Key endpoints

| Endpoint | Description |
| --- | --- |
| `GET /cog/info` | COG metadata (bounds, bands, CRS) |
| `GET /cog/viewer` | In-browser COG viewer |
| `GET /cog/tiles/{z}/{x}/{y}` | Slippy map tiles (XYZ) |
| `GET /cog/preview` | Thumbnail image |
| `GET /cog/statistics` | Band statistics |
| `GET /wcs` | OGC WCS 2.0.1 |
| `GET /wms` | OGC WMS 1.3.0 |

All endpoints accept a `url` parameter pointing to the COG file (local path or cloud URI).

## Key behaviours

- **On-demand tiling** — tiles are generated dynamically from COG internal overviews; no pre-tiling needed
- **Band selection** — use `bidx` to select one or more bands (e.g. `bidx=1`)
- **Cloud storage** — supports local paths and cloud URIs (`/vsicurl/`, `s3://`, `gs://`) via GDAL
- **Tile matrix sets** — WebMercatorQuad (EPSG:3857, default) and WorldCRS84Quad

## Configuration

| Variable | Description |
| --- | --- |
| `GDAL_DISABLE_READDIR_ON_OPEN` | Set `EMPTY_DIR` for faster COG access |
| `CPL_VSIL_CURL_CACHE_SIZE` | VSICURL cache size for remote COGs |

## COG requirements

- Must be in Cloud-Optimized GeoTIFF format (internal tiling + overviews)
- STAC metadata is managed separately by `gis-pipeline` and stored in PostGIS
- Recommended compression: DEFLATE or LZW
