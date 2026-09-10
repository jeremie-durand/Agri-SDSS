# gis-pipeline

Geospatial ETL service. Discovers multi-format geodata in `data/input/`, validates and harmonizes it, then writes to PostGIS, DuckDB/GeoParquet, COGs, and the STAC catalog.

**Requires**: PostGIS and STAC API running

## Run

```bash
docker compose exec gis-pipeline python3 -m gis_pipeline.main
```

## What it does

- Ingests `.shp`, `.geojson`, `.gpkg`, `.gdb`, `.csv`, `.tif` / `.tiff`
- Reprojects all data to EPSG:4326 (configurable)
- Vectors → PostGIS tables + GeoParquet files
- Rasters → Cloud-Optimized GeoTIFFs + STAC items

## Configuration

`config.yaml` — pipeline settings; env vars override individual keys  
`STAC_API_URL` — where to publish STAC items (default: `http://stac-api:8081`)

## Test

```bash
make test-gis-pipeline
```

## Docs

→ [Architecture](docs/ARCHITECTURE.md)  
→ [CLI arguments](docs/ARGS.md)
