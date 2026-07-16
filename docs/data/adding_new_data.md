# Adding New Data Sources

Complete step-by-step guide for integrating new datasets.

## Overview

This guide walks through the process of adding a new data source from discovery through API publication.

## Prerequisites

- Docker & Docker Compose installed and running
- Access to gis-pipeline source code

## Step 1: Research & Document

### 1.1 Identify Data Source

Find your dataset:
- Note the download URL
- Document metadata: CRS, format, geometry type
- Check license
- Verify update frequency and data quality

### 1.2 Create Source Documentation

Create a file in `docs/data/sources/SOURCENAME.md` following the format of existing docs:

**Minimal template:**
```markdown
# SOURCENAME - Full Dataset Title

Brief description (1-2 sentences)

## Overview
- Type: vector|raster|tabular
- Format: .shp|.tif|.csv|.gpkg
- CRS: EPSG:xxxx
- Resolution: xx (for raster)
- Update Frequency: daily|monthly|annual|one-time

## Using [SOURCENAME] Data
- Example queries
- Common use cases

## Source Information
- External URL: https://...
- Publisher: Organization Name
- License: OGL-Q
```

**See existing examples:** [GRHQ.md](sources/GRHQ.md), [SIIGSOL.md](sources/SIIGSOL.md)

### 1.3 Update CATALOG.md

Add entry to [docs/data/CATALOG.md](CATALOG.md):

```markdown
| SOURCENAME | Type | Format | CRS | Update | Status | Details |
|-----------|------|--------|-----|--------|--------|---------|
| NEW-SOURCE | vector/raster/tabular | .fmt | 4326 | freq | 🟡 Testing | [Link](sources/SOURCENAME.md) |
```

### 1.4 Add to the frontend catalog

Add an entry to [frontend/home/html/js/catalog.json](../../frontend/home/html/js/catalog.json) so the `/data` page shows the dataset with curated metadata (bilingual name/description, license, source link) and a live ingestion status. The `match[].idPattern` regexes link the entry to the live collection ids (`postgis` ids are `public.<table>`; `parquet` ids are the file stem; `stac` ids are the collection id). Datasets fetched on demand (not ingested) use `"type": "external"`. Ingested collections matching no entry appear automatically under "Other datasets in the backend".

## Step 2: Prepare Data

### 2.1 Download & Validate

```bash
# Create directory for new source
mkdir -p data/input/vector/my_source/  # or raster/ for GeoTIFF
cd data/input/vector/my_source/

# Download dataset
wget https://example.com/dataset.zip
unzip dataset.zip

# Inspect file
ogrinfo dataset.shp  # For vector
gdalinfo dataset.tif  # For raster
```

### 2.2 Check Data Structure

**For vector data:**
```bash
# List layers/fields
ogrinfo -summary dataset.shp

# Check geometry type and CRS
ogrinfo dataset.shp | grep -E "Geometry|EPSG"

# Get bounds
ogr2ogr -f GeoJSON /vsistdout/ dataset.shp | jq '.features[0]'
```

**For raster data:**
```bash
# Get raster info
gdalinfo dataset.tif | head -30

# Check bands
gdalinfo -checksum dataset.tif
```

**For tabular data:**
```bash
# Preview CSV structure
head -5 data.csv
wc -l data.csv  # Row count
```

### 2.3 Document Technical Details

Update your `docs/data/sources/SOURCENAME.md` with:

```markdown
## Data Details

| Property | Value |
|----------|-------|
| **Type** | vector/raster/tabular |
| **Format** | .shp/.tif/.csv/.gpkg |
| **CRS** | EPSG:xxxx |
| **Field Count** | N |
| **Feature Count** | M |
| **File Size** | X MB |
| **Update Frequency** | daily/monthly/annual |
| **License** | OGL-Q |
```

## Step 3: Configure Pipeline Ingestion

### 3.1 Add to Pipeline Configuration

Edit [gis-pipeline/config.yaml](../../gis-pipeline/config.yaml):
- Set `pipeline.STAC_COLLECTION_ID` to your collection id (e.g., `my_source`).
- Paths are already set for containers (`/data/input`, `/data/output/raster_cog`); adjust only if your deployment differs.

Example:

```yaml
pipeline:
  STAC_COLLECTION_ID: my_source
```

## Step 4: Test Data Ingestion

### 4.1 Run Pipeline on Test Data

```bash
# Build pipeline image
docker compose build gis-pipeline

# Test ingestion on a small input directory
docker compose run --rm gis-pipeline \
  python3 -m gis_pipeline.main \
  --input /data/input/my_source \
  --collection my_source
```

### 4.2 Check Logs

```bash
# View pipeline logs
docker compose logs gis-pipeline | tail -100

# Check for errors
docker compose logs gis-pipeline | grep -i "error\|warning"

# Detailed logs
docker compose exec gis-pipeline tail -f logs/*.log
```

### 4.3 Verify PostGIS Import

```bash
# Connect to PostgreSQL
docker compose exec database psql -U agri_sdss -d agri_sdss

# Check tables
SELECT table_name FROM information_schema.tables 
WHERE table_name ILIKE '%my_source%';

# Count features
SELECT COUNT(*) FROM my_source_features;

# Check geometry
SELECT ST_SRID(geometry), GeometryType(geometry) FROM my_source_features LIMIT 1;
```

## Step 5: Publish & Validate

### 5.1 Full Data Ingestion

```bash
# Process complete dataset
docker compose run --rm gis-pipeline \
  python3 -m gis_pipeline.main \
  --collection my_source
```

### 5.2 Verify STAC Publication

```bash
# Check STAC API
curl http://<host>:8081/collections

# Get collection
curl http://<host>:8081/collections/my-source

# Browse items
curl http://<host>:8081/collections/my-source/items?limit=10
```

### 5.3 Test Vector/Raster APIs

**Vector API (OGC Features):**
```bash
# Get features
curl http://<host>:8083/collections/my_source/items?limit=10

# Spatial query
curl "http://<host>:8083/collections/my_source/items?bbox=-71.5,45.0,-71.0,45.5"
```

**Raster API (WCS):**
```bash
# Get raster info
curl http://<host>:8082/cog/info?url=data/my_source.tif

# Get tile
curl "http://<host>:8082/cog/tiles/10/512/512.png?url=data/my_source.tif"
```

### 5.4 Run Tests

```bash
# Run all pipeline tests
make test-gis-pipeline

# Run a single test file
docker compose run --rm gis-pipeline pytest gis_pipeline/test/ -k my_source -v
```

## Quick Checklist

- [ ] Data source researched and documented
- [ ] Data downloaded and validated
- [ ] Pipeline configuration added
- [ ] Data successfully ingested
- [ ] PostGIS tables verified
- [ ] STAC metadata created
- [ ] APIs tested (Vector/Raster/STAC)
- [ ] Frontend catalog entry added (`frontend/home/html/js/catalog.json`)
- [ ] Documentation completed
- [ ] Tests pass
- [ ] CATALOG updated

## Next Steps

- See [Data Source Catalog](CATALOG.md) to verify your entry was added
- Check the [PostGIS schema reference](postgis_schema.md) for the table layout created by the pipeline
- Review the [gis-pipeline CLAUDE.md](../../gis-pipeline/CLAUDE.md) for ingestion rules and column conventions
