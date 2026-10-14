# CLAUDE.md — gis-pipeline

Service guide for `gis-pipeline`. It specializes the [root CLAUDE.md](../CLAUDE.md)
and wins wherever the two differ; everything the root file says still applies
unless overridden here.

## Service Overview

Batch ETL CLI: discovers geodata under `data/input/`, validates and harmonizes
it, then writes vectors to PostGIS + GeoParquet and rasters to COGs + PostGIS
metadata + the STAC API. It has no HTTP server; the container idles
(`sleep infinity`) and the pipeline runs on demand.

- Diagrams, module map and extension examples:
  [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Where it disagrees with the
  code, trust the code, and fix the doc when you touch that area.
- CLI arguments: [docs/ARGS.md](docs/ARGS.md) — generated, never edit by hand.
- PostGIS table layouts: [docs/data/postgis_schema.md](../docs/data/postgis_schema.md).

## Common Commands

Run from the repo root.

```bash
# Run the pipeline (defaults come from config.yaml)
docker compose exec gis-pipeline python3 -m gis_pipeline.main
docker compose exec gis-pipeline python3 -m gis_pipeline.main \
  --input /data/input --crs 4326 --collection my_collection

make test-gis-pipeline    # Whole suite (rebuilds the image)
make generate-args        # After any CLI argument change — CI diffs ARGS.md

# Single test (the suite lives at gis_pipeline/test/ inside the container)
docker compose run --rm gis-pipeline pytest \
  gis_pipeline/test/modules/processing/test_geoprocessing_vector.py::test_name -v
```

The Compose service builds the `test` target and bind-mounts `src/gis_pipeline`,
`test/`, `config.yaml` and `docs/`. Python changes are therefore live without a
rebuild. Rebuild only when you change requirements or the `Dockerfile`, which
also builds GDAL 3.11 from source and pins `numpy` in two places that must
match.

## Structure

```text
src/gis_pipeline/
  main.py                 CLI parser + vector/raster orchestration + run report
  generate_args_md.py     Writes docs/ARGS.md from parse_args(return_parser=True)
  core/
    config.py             Config class, pydantic env settings, public URL builders
    exceptions.py         GISPipelineError hierarchy
    logging_setup.py      setup_logging(), handle_error()
    utils.py              harmonize_name(), report and log-section helpers
  modules/
    io_tools/input_data.py      discover_geodata, read_csv_file, GPKG FK extraction
    processing/geoprocessing.py GeoprocessingVector, GeoprocessingRaster, GEE stamping
    processing/processing_stac.py  STAC item/collection builders, StacApiClient
    db/pg_utils.py        PostGISManager (+ GIDValidator, TypeMapper, SchemaBuilder,
                          DataInserter)
    db/duckdb_utils.py    DuckDBManager: Parquet/GeoParquet export, chunk finalize
    db/materialize.py     RTree-indexed .duckdb build from a GeoParquet file
    db/materialize_trigger.py  Build + notify vector-api after a GeoParquet write
  services/mapping.py     Enums: formats, column aliases, nulls, CRS overrides, …
  resources/              som_field_id_to_gid.csv (GEE FIELD_ID -> gid lookup)
test/                     Mirrors src/ layout; conftest.py holds shared fixtures
scripts/                  entrypoint.sh, prepare_som_data.py and
                          build_field_id_map.py (host-side data prep),
                          gee_sentinel2_feature_extraction.js (GEE Code Editor)
config.yaml               Pipeline defaults: GLOBAL_CRS, collection ID, paths
```

## Configuration

- `config.yaml` holds pipeline defaults: `GLOBAL_CRS`, `STAC_COLLECTION_ID`,
  input/COG/log paths.
- Environment variables are validated at import time by pydantic-settings in
  `core/config.py`. `POSTGRES_PASS` is required, so importing `Config` fails
  without it. Compose maps the app role (`DB_USER`/`DB_PASS`) onto
  `POSTGRES_USER`/`POSTGRES_PASS`, so the pipeline never runs as superuser.
- Read settings through `Config`, not `os.getenv`. The only exception is
  `LOG_LEVEL` in `logging_setup.py`.
- **Public URLs**: STAC hrefs come only from `public_cog_url`,
  `public_preview_url` and `public_tilejson_url` in `core/config.py`. Never
  build a URL from a container path. `public_cog_url` is part of the `/cog`
  route contract guarded by `make test-repo-consistency`.
- `VECTOR_API_URL` unset means the materialize trigger is silently skipped.

## Pipeline Behaviour

Keep these invariants when changing processing code.

### Vector

- Non-spatial CSVs (no lat/lon aliases) go straight to DuckDB Parquet and
  skip PostGIS.
- Spatial CSVs load in one shot. Every other format is read **layer by layer
  in chunks of `CHUNK_SIZE` (50 000) rows** to bound memory:
  - the first chunk uses `override_method="replace"` and later chunks use
    `"append"`;
  - `gid_offset` keeps GIDs unique across chunks;
  - chunk GeoParquet parts are staged under `.chunks/<table>/`, then combined by
    `DuckDBManager.finalize_chunked_geoparquet()`.
- `insert_table_data()` mutates `gid` in place to apply the offset. The
  GeoParquet export relies on that, so do not add a defensive `.copy()`.
- Per-table steps, in order: `validate_vector_data` → `harmonize_gdf` →
  `clean_geometries_gdf` → `harmonize_crs_gdf` → PostGIS → GeoParquet →
  `trigger_materialize_and_notify`.
- QGIS internal layers (`QGISInternalLayers`) are skipped. GPKG foreign keys
  are re-applied after all layers of the file are loaded.
- After all vectors, `stamp_gee_flags_on_field_boundaries()` sets `gee_field_id`
  and `has_gee_data` on `som_field_boundaries` and rewrites its GeoParquet so
  both stores agree. GEE `FIELD_ID` is **not** the platform `gid`: the two are
  translated through `resources/som_field_id_to_gid.csv`, which
  `scripts/build_field_id_map.py` regenerates from the source layers.
- Tables are **replaced** each run, not upserted.

### Raster

- Target CRS is `--crs`, unless the file stem matches a
  `RasterTargetCRSOverrides` keyword (e.g. `siigsol` → EPSG:32198).
- Same source and target CRS → `gdal_translate`, so there is no resampling pass.
  Otherwise `gdalwarp` with bilinear resampling. Pass `near` for categorical
  rasters.
- COG profile `default`: DEFLATE, BIGTIFF=YES, overviews AUTO. Output is
  `<harmonized_name>_cog.tif` in `Config.RASTER_COG_PATH`.
- `GeoprocessingRaster._render_params` computes the `bidx` and `rescale` that
  TiTiler needs. Keep it in step with the href rules in
  [../docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md#stac-asset-hrefs).
- STAC datetime priority: metadata keys/tags → shallow metadata values →
  filename (`YYYYMMDD[_T-]HHMMSS`, `YYYYMMDD`, bare `19xx`/`20xx` year) →
  `Config.DEFAULT_DATETIME` (1950-01-01 UTC).
- The collection is POSTed once per run. Each item is POSTed, then PUT on
  `409`, so re-runs do not duplicate.
- Every STAC payload goes through `_clean_metadata()`, which converts numpy
  scalars, NaN/Inf and dates to JSON-safe values.

### Ingestion rules

- **GID**: existing `gid` (after alias renaming) → a `RangeIndex` shifted to
  start at 1 → generated sequence. Null GIDs are repaired, not dropped. A
  PRIMARY KEY is added afterwards so TiPg detects it.
- **Identifiers**: `harmonize_name()` truncates to
  `POSTGRES_MAX_NAME_LENGTH` (50) and appends `_` plus 6 MD5 hex characters.
- **Geometry repair**: `shapely.make_valid`, keeping only parts of the input
  dimension. A geometry left with none is dropped with a warning. Overlaps are
  logged, never dropped.
- `services/mapping.py` enums are the single source of truth for formats,
  column aliases, null tokens, CSV source CRS, raster CRS overrides, naming
  patterns and SQL types. Extend them there, never inline.

### Failure model

- One bad file or layer must not abort the run. `main.py` catches per-layer
  and per-file errors and counts them in the run report.
- A raster batch fails (`RasterProcessingError`) only if **every** raster
  fails.
- STAC publishing, the materialize trigger, the vector-api notification and
  GEE stamping are best-effort: they log and continue, never raise.
- Raise the service hierarchy in `core/exceptions.py` (`GISPipelineError` →
  `VectorProcessingError`, `RasterProcessingError`, `ConfigurationError`).
  Wrap unexpected errors at the pipeline boundary with `raise … from e`.
- `handle_error(logger, msg, exc_class)` logs with a traceback and then raises.
  Use it for fatal paths.

## Cross-Service Coupling

- `modules/db/materialize.py` is a copy of `vector-api/src/materialize.py` (the
  two images share no package). Keep the SQL identical across both. There is
  no consistency test yet, so check the other copy by hand when editing.
- After writing `<table>.parquet`, the trigger builds `<table>.duckdb.new`,
  renames it over `<table>.duckdb`, then POSTs
  `{VECTOR_API_URL}/parquet/collections/{table}/invalidate`. Build-then-rename
  is required: DuckDB locks readers out while a write connection is open.
- The STAC API is reached at `STAC_API_URL` (internal service name), never
  through the public origin.

## Logging

This overrides the root rule on log formatting.

- Use `structlog.get_logger()` at module level. `setup_logging()` is called
  **once**, in `main()`, which also binds `run_id`.
- For new and changed code, the event is a snake_case name and the context goes
  in kwargs. Do not use f-strings or `%s`:

  ```python
  logger.warning("stac_publish_failed", item=item_id, error=str(exc))
  ```

  Existing f-string log calls are debt. Convert them when you touch those
  lines, not in drive-by sweeps.
- Bind per-item context with
  `structlog.contextvars.bound_contextvars(file=…)` inside loops, not by
  repeating kwargs.
- Logs go to stdout and to a rotating `app.log` under `Config.LOG_DIR`. That
  file handler is silently skipped when the directory is not writable (CI).

## Testing

- Tests are unit tests with mocked I/O: no live PostGIS or STAC API calls.
  DuckDB runs in-process against temp files.
- Mock with `unittest.mock.patch`/`MagicMock` and `monkeypatch`. Use in-memory
  GeoDataFrames and `tmp_path` rasters. `responses` is used only for STAC HTTP
  tests.
- Add shared fixtures to `test/conftest.py` rather than per-file copies.
- Mark new tests `@pytest.mark.unit` or `@pytest.mark.mocked`. Many existing
  tests are unmarked; do not bulk-add markers.
- New rules need the normal path, an edge case (empty frame, null geometry,
  constant raster band) and the error path.
- `test/test_main.py` and `test/test_orchestration.py` cover `main.py`. Update
  them when orchestration or the report counters change.

## Key Patterns

- **Deferred imports in `main.py` are intentional.** Keep the heavy stack
  (fiona, geopandas, the DB managers) out of module scope so `--help`,
  `generate_args_md` and `make smoke-entrypoints` stay light. This exception
  applies to `main.py` only; every other module imports at top level.
- Use the context managers for DB access: `with PostGISManager() as pg:` and
  `with DuckDBManager() as db:`.
- Run GDAL work through the existing command builders (`_build_gdalwarp_command`,
  `_build_gdaltranslate_cog_command`) and `_warp_raster`. Do not add new
  subprocess call sites.
- No i18n here: the pipeline has no user-facing API, so messages stay in
  English and never go through `agri_i18n`.
