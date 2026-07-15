# PostGIS Schema

Authoritative table layouts created by the pipeline for vector data and raster STAC metadata, based on the implementation in `gis_pipeline`.

## Conventions

- CRS: EPSG:4326 for all geometries
- Table names: must match `^[A-Za-z_][A-Za-z0-9_]*$` and are truncated to `POSTGRES_MAX_NAME_LENGTH` (50)
- Defaults: no indexes or NOT NULL constraints are added automatically
- **ID Column Standard**: All tables use `gid` as the primary key column name

### ID Column Normalization

The pipeline automatically normalizes ID column names to the standard `gid` name to ensure consistency across PostGIS tables and Parquet exports. This normalization occurs during:
- PostGIS table ingestion (via `GeoDataProcessor._rename_gdf_columns()`)
- Parquet file export (via `DuckDBManager.save_gdf_to_geoparquet()` and `save_table_to_geoparquet()`)

**Supported ID Column Aliases** (automatically renamed to `gid`):
- `id`
- `id_station`
- `station_id`
- `no`

**Example log messages:**
```
INFO - Automatically renamed ID column 'id' to 'gid'
INFO - Renamed column 'station_id' to 'gid' during Parquet export
```

**Behavior:**
- If input data contains any of the supported aliases, it will be renamed to `gid`
- If `gid` already exists alongside an alias, the alias and canonical columns are compared value-by-value:
  - **Identical values** → the alias column is silently dropped (redundant)
  - **Different values** → a `ValueError` is raised; the pipeline cannot determine the authoritative source
- If multiple aliases exist (e.g., both `id` and `station_id`) with no explicit `gid`, the first alias encountered (by column order) is renamed to `gid`, then each remaining alias is compared against it using the same identity check above
- Original input data remains unmodified; renaming applies only to processed copies
- Parquet files transparently normalize ID columns on export, ensuring all archived data uses `gid`

## Vector Data Tables

Created by `PostGISManager.insert_table_data()` with base columns from `VectorPostGISColumns` and inferred attributes from the input `GeoDataFrame`.

Base columns:

- gid: INTEGER PRIMARY KEY (autoincrement)
- geometry: geometry(Geometry, 4326)
- datetime: TIMESTAMP WITH TIME ZONE
- metadata: JSONB

Type inference for additional attributes:

- datetime-like → TIMESTAMP WITH TIME ZONE
- integer → TEXT (safe default)
- float → TEXT (safe default)
- object with ≥70% dict/list values → JSONB, else TEXT
- column named `geometry` → geometry(Geometry, 4326)

Example DDL:

```sql
CREATE TABLE public.my_vector_table (
	gid INTEGER PRIMARY KEY,
	geometry geometry(Geometry,4326),
	datetime TIMESTAMP WITH TIME ZONE,
	metadata JSONB
	-- + additional inferred columns (TEXT/JSONB/TIMESTAMPTZ)
);
```

Recommended spatial index (optional):

```sql
CREATE INDEX my_vector_table_geom_gix
	ON public.my_vector_table USING GIST (geometry);
```

## Raster STAC Metadata Table

Created by `PostGISManager.insert_cog_metadata()` using `RasterStacColumns`.

Columns:

- gid: TEXT PRIMARY KEY
- datetime: TIMESTAMP WITH TIME ZONE
- bbox: FLOAT[]  -- [minx, miny, maxx, maxy]
- geometry: geometry(Polygon, 4326)
- file_url: TEXT
- metadata: JSONB

Example DDL:

```sql
CREATE TABLE public.raster_stac (
	gid TEXT PRIMARY KEY,
	datetime TIMESTAMP WITH TIME ZONE,
	bbox FLOAT[],
	geometry geometry(Polygon,4326),
	file_url TEXT,
	metadata JSONB
);
```

Upsert behavior on `gid` is implemented in the pipeline when inserting COG metadata.

## Notes

- Tables are created via SQLAlchemy from the mappings in [gis-pipeline/src/gis_pipeline/services/mapping.py](../../gis-pipeline/src/gis_pipeline/services/mapping.py).
- The pipeline does not auto-create non-primary indexes; add GIST indexes for geometry columns where spatial queries are expected.
