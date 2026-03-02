# Earth Observation Data Integration - Sentinel-2 via openEO

This documentation describes the `sentinel-fetch` PyGeoAPI process for fetching Sentinel-2 data via openEO.

**Process implementation**: [eo_sentinel_fetch.py](../processes/eo_sentinel_fetch.py)

## Overview

The `sentinel-fetch` process:

1. Accepts a farm polygon (GeoJSON or database ID)
2. Fetches Sentinel-2 L2A data from Copernicus Dataspace via openEO
3. Calculates vegetation indices (NDVI, EVI, SAVI) or other products
4. Converts results to Cloud Optimized GeoTIFF (COG)
5. Stores metadata in STAC catalog and PostGIS
6. Serves tiles via TiTiler (raster-api)

## Setup

**Authentication Required**: Follow the setup guide [OPENEO_SETUP.md](OPENEO_SETUP.md) to configure OpenEO authentication.

Rebuild the pygeoapi service:

```bash
docker compose build pygeoapi
docker compose up -d pygeoapi
```

## Usage

### Process Endpoint

Access the process at:
```
http://localhost:5000/processes/sentinel-fetch
```

### Example 1: Fetch NDVI for Farm by ID (Real BDPPAD Farm)

```json
{
  "inputs": {
    "farm_id": 4,
    "temporal_extent": ["2024-06-01", "2024-08-31"],
    "output_products": ["ndvi"],
    "aggregation_method": "median",
    "cloud_cover_max": 20
  }
}
```

### Example 2: Fetch Multiple Products with Custom Geometry

```json
{
  "inputs": {
    "farm_geometry": {
      "type": "Polygon",
      "coordinates": [[
        [-71.5, 45.5],
        [-71.4, 45.5],
        [-71.4, 45.6],
        [-71.5, 45.6],
        [-71.5, 45.5]
      ]]
    },
    "temporal_extent": ["2024-07-01", "2024-07-31"],
    "output_products": ["ndvi", "evi", "true_color"],
    "aggregation_method": "max",
    "cloud_cover_max": 15
  }
}
```

### Example 3: Using URL (Large Farm)

```bash
curl -X POST "http://localhost:5000/processes/sentinel-fetch/execution" \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {
      "farm_id": 75,
      "temporal_extent": ["2024-06-01", "2024-08-31"],
      "output_products": ["ndvi", "evi", "savi"],
      "aggregation_method": "max",
      "cloud_cover_max": 15
    }
  }'
```

### Example 4: Small Farm with True Color

```bash
curl -X POST "http://localhost:5000/processes/sentinel-fetch/execution" \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {
      "farm_id": 27,
      "temporal_extent": ["2024-07-01", "2024-07-31"],
      "output_products": ["ndvi", "true_color"],
      "aggregation_method": "median"
    }
  }'
```

## Input Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `farm_geometry` | GeoJSON | Conditional* | Farm boundary as Polygon or MultiPolygon |
| `farm_id` | integer | Conditional* | Database ID to lookup farm from `bdppad_2024_4326_sample_stac` |
| `temporal_extent` | array[string] | Yes | `[start_date, end_date]` in ISO 8601 format |
| `output_products` | array[string] | Yes | Products to generate: `raw_bands`, `ndvi`, `evi`, `savi`, `true_color` |
| `aggregation_method` | string | No | Temporal aggregation: `median` (default), `max`, `min`, `mean` |
| `cloud_cover_max` | number | No | Max cloud cover % (default: 20) |

\* Either `farm_geometry` or `farm_id` must be provided (not both)

## Output Products

- **NDVI**: Normalized Difference Vegetation Index - `(NIR - Red) / (NIR + Red)`
- **EVI**: Enhanced Vegetation Index - `2.5 * (NIR - Red) / (NIR + 6*Red - 7.5*Blue + 1)`
- **SAVI**: Soil Adjusted Vegetation Index - `1.5 * (NIR - Red) / (NIR + Red + 0.5)`
- **true_color**: RGB composite (B04/B03/B02)
- **raw_bands**: Original Sentinel-2 bands (B02, B03, B04, B08)

## Response Format

```json
{
  "stac_item_id": "sentinel2_farm_4_2024-06-01_2024-08-31",
  "assets": {
    "ndvi": "/data/sentinel2_farm_4_ndvi_2024-06-01_2024-08-31_a1b2c3d4.tif",
    "evi": "/data/sentinel2_farm_4_evi_2024-06-01_2024-08-31_e5f6g7h8.tif"
  },
  "preview_url": "http://raster-api:8082/cog/preview.png?url=/data/sentinel2_farm_4_ndvi_2024-06-01_2024-08-31_a1b2c3d4.tif&rescale=0,1",
  "bbox": [-71.5, 45.5, -71.4, 45.6],
  "temporal_extent": ["2024-06-01", "2024-08-31"],
  "area_km2": 98.5
}
```

## Data Storage

- **COG Files**: Stored in `/data/output/raster_cog/`
- **STAC Metadata**: `pgstac.collections` → `sentinel2_eo_products`
- **Product Metadata**: `public.sentinel2_products` table

## Viewing Results

TiTiler preview: `http://localhost:8082/cog/preview.png?url=/data/{filename}&rescale=0,1`

STAC Browser: `http://localhost:8085`

## References

- [openEO Documentation](https://openeo.org/documentation/1.0/)
- [Copernicus Dataspace](https://dataspace.copernicus.eu)
