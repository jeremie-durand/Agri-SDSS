# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this service.

## Purpose

Geospatial ETL pipeline: ingest multi-format geodata files, validate and harmonize them, then persist to PostGIS, DuckDB/GeoParquet, and the STAC API. Architecture, data-flow diagrams, and design rationale are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md); table layouts are in [docs/data/postgis_schema.md](../docs/data/postgis_schema.md).

Non-spatial CSVs (no lat/lon columns) are written directly to DuckDB Parquet and skip the geo pipeline.

## Supported Input Formats

| Format | Extension | Handler |
| --- | --- | --- |
| Shapefile | `.shp` | `fiona` / `geopandas` |
| GeoJSON | `.geojson` | `geopandas` |
| GeoPackage | `.gpkg` | `geopandas` |
| File Geodatabase | `.gdb` | `fiona` |
| CSV (spatial) | `.csv` | `read_csv_file()` + lat/lon detection |
| CSV (non-spatial) | `.csv` | `read_csv_file()` → DuckDB only |
| GeoTIFF / COG | `.tif`, `.tiff` | `rasterio` + `gdalwarp` |

## Output Targets

| Target | Content | Technology |
| --- | --- | --- |
| PostGIS table | Vector features (schema: gid, geometry, datetime, metadata JSONB) | SQLAlchemy + psycopg |
| GeoParquet file | Vector features in columnar format | DuckDB spatial extension |
| COG file | Cloud-Optimized GeoTIFF at `/data/output/raster_cog/` | GDAL `gdalwarp` subprocess |
| STAC API | STAC Items + Collection describing each COG | HTTP POST/PUT via `requests` |

## Core Processing Steps

### Vector

1. `convert_vector_files_to_gdf()` — open all vector files into GeoDataFrames
2. `validate_vector_data()` — check CRS presence, geometry validity, geometry type consistency
3. `harmonize_gdf()` — `_rename_gdf_columns()` → drop duplicates/nulls → cast types
4. `clean_geometries_gdf()` — repair invalid geometries (`shapely.make_valid`), detect overlaps, drop null geoms
5. `harmonize_crs_gdf()` — reproject to target EPSG (default 4326)
6. `PostGISManager.insert_table_data()` — upsert to PostGIS
7. `DuckDBManager.save_gdf_to_geoparquet()` — write GeoParquet

### Raster

1. `validate_raster()` — check CRS, band count, nodata value
2. `process_raster_to_cog()` — `gdalwarp` with LZW/DEFLATE compression and tiling
3. `prepare_cog_metadata_for_stac()` — extract band descriptions, datetime, bounding box
4. `PostGISManager.insert_cog_metadata()` — persist COG record
5. `build_stac_items_from_cog()` / `build_stac_collection_from_items()` — assemble STAC objects
6. `StacApiClient.post_collection()` + `StacApiClient.upsert_items()` — publish to STAC API

## Ingestion Rules

- **GID**: must be an integer primary key. Priority: existing `gid` column → first integer column → auto-generate sequential integers. Nulls in GID are repaired.
- **Column names**: normalized via `ColumnMappings` enum (case-insensitive lookup). Aliases like `"id"`, `"lat"`, `"lon"`, `"date"` are mapped to canonical names (`gid`, `latitude`, `longitude`, `datetime`).
- **Null values**: variants (`""`, `"NA"`, `"n/a"`, `"None"`, `np.nan`) replaced with Python `None` via `AttributeNullValues` enum.
- **Identifiers**: table/file names are truncated to fit Postgres limits with a 6-char MD5 suffix to preserve uniqueness (`_harmonize_name_gdf()`).
- **CSV CRS**: source CRS for CSVs without a projection file is looked up in `CSVDataRegistryForSourceCRS` enum by file stem.

## CRS and Geometry Handling

- All data is reprojected to `Config.GLOBAL_CRS` (default EPSG:4326) via `pyproj`.
- Invalid geometries are repaired with `shapely.make_valid` before insertion. Only parts
  matching the input dimension are kept, so a repaired polygon never becomes a
  GeometryCollection carrying the dangling lines that caused the invalidity. A geometry
  with no part of its own dimension left is dropped with a warning.
- Overlapping geometries are detected and logged (not dropped).
- Rasters are reprojected via `gdalwarp` with the same target CRS.

## Metadata and STAC Generation

Datetime extraction for STAC items follows this priority:

1. Metadata tags (`TIFFTAG_DATETIME`, `acquisition_date`, etc.)
2. aux.xml band descriptions
3. Filename regex patterns: `YYYYMMDD`, `YYYY-MM-DD`, `YYYY_MM_DD`, `YYYYMM`, `YYYY`
4. Fallback: `DefaultMetadata.DATETIME`

STAC Collections are created once per pipeline run (keyed by `Config.STAC_COLLECTION_ID`). Items are upserted (PUT) to allow re-runs without duplicates.

All metadata serialized to STAC must pass `_clean_metadata()`, which recursively converts numpy scalars, NaN/Inf, and dates to JSON-safe types.

## Error Handling and Validation

- All critical errors go through `handle_error(logger, msg, exc_class)` in `core/logging_setup.py` — logs structured context then raises.
- **Logging standard**: every module uses `structlog.get_logger()` directly — never `setup_logging()`. `setup_logging()` is called **once** in `main()` to configure handlers and bind `run_id`. Per-item context is bound with `structlog.contextvars.bound_contextvars(key=value)` inside processing loops so each iteration carries its own context and it is cleared automatically. Example:

  ```python
  import structlog
  logger = structlog.get_logger()

  for vector_file in vector_files:
      with structlog.contextvars.bound_contextvars(file=vector_file.name):
          logger.info("Processing file")  # → {file: "foo.shp", run_id: "a1b2c3d4", ...}
  ```

- Custom exception: `GeoprocessingPipelineError`.
- The main pipeline catches per-file errors and increments a failure counter, so one bad file does not abort the run.
- STAC API client uses `urllib3.Retry` with backoff for transient HTTP errors.

## Module Responsibilities

Module-by-module breakdown is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#module-structure). Two rules to keep in mind when editing:

- `services/mapping.py` enums are the single source of truth for formats, column aliases, null values, naming patterns, and GDAL types — extend them there, never inline.
- `generate_args_md.py` auto-generates `docs/ARGS.md` from argparse — run `make generate-args` after changing CLI args (CI fails if out of sync).

## Service Layout

| File | Purpose |
| --- | --- |
| `Dockerfile.gis-pipeline` | Production image |
| `requirements-gis-pipeline.txt` | Runtime dependencies |
| `requirements-gis-pipeline-test.txt` | Test-only dependencies (installed on top of runtime) |
| `test/` | All pytest tests for this service |

## Testing Guidelines

All tests are **unit tests with mocked external services** — no live PostGIS, DuckDB, or STAC API calls.

| Area | File | Mocking approach |
| --- | --- | --- |
| PostGIS | `test/modules/db/test_pg_utils.py` | `unittest.mock.patch` on SQLAlchemy engine/connection |
| DuckDB | `test/modules/db/test_duckdb_utils.py` | Mocked DuckDB connection and cursor |
| I/O | `test/modules/io_tools/test_input_data.py` | Temp directories with synthetic files |
| Vector processing | `test/modules/processing/test_geoprocessing_vector.py` | In-memory GeoDataFrames (points, polygons, mixed CRS) |
| Raster processing | `test/modules/processing/test_geoprocessing_raster.py` | Mocked `rasterio.open`, synthetic numpy arrays |
| STAC generation | `test/modules/processing/test_processing_stac.py` | `responses` library for HTTP mocking |

When adding a new transformation or rule, add a unit test that covers the normal path, an edge case (empty data, null geometry), and the error path.

## Example Workflow

```bash
# Run the pipeline on a directory of input files
docker compose run --rm gis-pipeline python -m gis_pipeline.main \
  --input /data/input \
  --crs 4326 \
  --collection my_collection

# After modifying CLI arguments, regenerate ARGS.md
make generate-args

# Run only pipeline tests
make test-gis-pipeline

# Run a single test
docker compose run --rm gis-pipeline pytest gis_pipeline/test/modules/processing/test_geoprocessing_vector.py::test_harmonize_gdf -v
```
