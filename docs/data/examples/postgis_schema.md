# PostGIS Schema

Authoritative table layouts created by the pipeline for vector data and raster STAC metadata, based on the implementation in `gis_pipeline`.

## Conventions

- CRS: EPSG:4326 for all geometries
- Table names: must match `^[A-Za-z_][A-Za-z0-9_]*$` and are truncated to `POSTGRES_MAX_NAME_LENGTH` (50)
- Defaults: no indexes or NOT NULL constraints are added automatically

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

- Tables are created via SQLAlchemy from the mappings in [gis-pipeline/src/gis_pipeline/services/mapping.py](../../../gis-pipeline/src/gis_pipeline/services/mapping.py).
- The pipeline does not auto-create non-primary indexes; add GIST indexes for geometry columns where spatial queries are expected.
