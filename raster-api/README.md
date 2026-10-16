# raster-api

OGC raster service built on TiTiler. Serves Cloud-Optimized GeoTIFFs (COGs) as dynamic map tiles (XYZ, TileJSON, WMTS), previews, point values, and band statistics.

**Port**: 8082 | **Requires**: COG files in `data/output/raster_cog/`

Interactive API docs: `http://<host>/raster-api/api.html`

## Start

```bash
docker compose up -d raster-api
```

## Key endpoints

| Endpoint | Description |
| --- | --- |
| `GET /cog/info` | COG metadata (bounds, bands, CRS) |
| `GET /cog/viewer` | In-browser COG viewer |
| `GET /cog/tiles/{tileMatrixSetId}/{z}/{x}/{y}` | Slippy map tiles (XYZ) |
| `GET /cog/preview` | Thumbnail image |
| `GET /cog/statistics` | Band statistics |
| `GET /cog/point/{lon},{lat}` | Pixel values at a point |
| `GET /cog/{tileMatrixSetId}/tilejson.json` | TileJSON for web maps |
| `GET /cog/WMTSCapabilities.xml` | OGC WMTS capabilities |
| `GET /collections` | COG files available in the mounted data directory (custom route) |

All `/cog/*` endpoints take a `url` parameter pointing to the COG file. Local
files are addressed by their container path, e.g. `url=/data/<file>.tif`.
There are no WMS or WCS endpoints; the full route list is at `/raster-api/api`.

## Key behaviours

- **On-demand tiling** — tiles are generated dynamically from COG internal overviews; no pre-tiling needed
- **Band selection** — use `bidx` to select one or more bands (e.g. `bidx=1`)
- **Cloud storage** — supports local paths and cloud URIs (`/vsicurl/`, `s3://`, `gs://`) via GDAL
- **Tile matrix sets** — WebMercatorQuad (EPSG:3857, default) and WorldCRS84Quad

## Configuration

| Variable | Description |
| --- | --- |
| `APP_ROOT_PATH` | Public path prefix (`/raster-api`), passed to uvicorn `--root-path` |
| `RASTER_COG_DIR` | Directory listed by `/collections` (default `/data`) |
| `GDAL_CACHEMAX` | GDAL block cache size in MB (`200`) |
| `WEB_CONCURRENCY` | Number of uvicorn workers (`2`) |

## COG requirements

- Must be in Cloud-Optimized GeoTIFF format (internal tiling + overviews)
- STAC metadata is managed separately by `gis-pipeline` and stored in PostGIS
- Recommended compression: DEFLATE or LZW
