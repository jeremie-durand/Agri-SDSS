# data

Persistent data volumes for the MOS-GIS platform. Not a service — mounted into containers at runtime.

## Directory structure

```text
data/
├── input/
│   ├── vector/    ← drop Shapefiles, GeoJSON, GeoPackages, CSVs here
│   └── raster/    ← drop GeoTIFFs and georeferenced imagery here
├── output/
│   └── raster_cog/  ← COGs written by gis-pipeline
├── duckdb/           ← GeoParquet files written by gis-pipeline
└── pg/               ← PostgreSQL data volume
```

## Adding data

1. Copy your files into `data/input/vector/` or `data/input/raster/`
2. Run the pipeline:

```bash
docker compose exec gis-pipeline python3 -m gis_pipeline.main
```

Data is automatically discovered, validated, reprojected, and ingested.

## Docs

→ [Data catalog](../docs/data/CATALOG.md) — integrated datasets and sources  
→ [Adding new data](../docs/data/adding_new_data.md) — step-by-step guide  
→ [Data sources](../docs/data/sources/) — per-source documentation
