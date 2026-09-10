# Sentinel-2 Earth Observation — Query Specifications

Process: `POST /processes/sentinel-fetch/execution`

Fetches Sentinel-2 L2A imagery from the Copernicus Data Space (openEO backend) for a
farm area, computes vegetation indices, stores results as Cloud Optimized GeoTIFFs (COGs),
and publishes metadata to the STAC catalog.

**Implementation:** [eo_sentinel_fetch.py](../processes/eo_sentinel_fetch.py)

---

## Setup

**Authentication required.** Follow [OPENEO_SETUP.md](OPENEO_SETUP.md) to obtain a token.

```bash
# After setting OPENEO_REFRESH_TOKEN in .env:
docker compose build process-api
docker compose up -d process-api
```

The token expires ~30 days — regenerate with `scripts/get_openeo_token.sh`.

---

## Output products

| `output_products` value | Description | Bands used | Output range |
| --- | --- | --- | --- |
| `ndvi` | Normalized Difference Vegetation Index | B08 (NIR), B04 (Red) | −1 to 1 |
| `evi` | Enhanced Vegetation Index | B08 (NIR), B04 (Red), B02 (Blue) | typically 0 to 1 |
| `savi` | Soil Adjusted Vegetation Index | B08 (NIR), B04 (Red) | typically 0 to 1 |
| `true_color` | RGB composite | B04 (Red), B03 (Green), B02 (Blue) | reflectance |
| `raw_bands` | All bands unprocessed | B02, B03, B04, B08 | reflectance |

Multiple products can be requested in a single call.

### Index formulas

```text
NDVI = (NIR - Red) / (NIR + Red)

EVI  = 2.5 × (NIR - Red) / (NIR + 6×Red - 7.5×Blue + 1)

SAVI = 1.5 × (NIR - Red) / (NIR + Red + 0.5)
```

---

## Location

Exactly one of `farm_id` or `farm_geometry` must be provided — not both.

| Field | Type | Description |
| --- | --- | --- |
| `farm_id` | integer | PostGIS primary key — geometry is looked up from the table set in `FARM_TABLE_NAME` (`.env`) |
| `farm_geometry` | object | GeoJSON Polygon or MultiPolygon in EPSG:4326 |

---

## Parameters

| Parameter | Type | Required | Default | Constraints |
| --- | --- | --- | --- | --- |
| `farm_id` | integer | one of the two | — | PostGIS PK |
| `farm_geometry` | object | one of the two | — | GeoJSON Polygon / MultiPolygon |
| `temporal_extent` | array | yes | — | `["YYYY-MM-DD", "YYYY-MM-DD"]` |
| `output_products` | array | yes | — | ≥ 1 value from the products table |
| `aggregation_method` | string | no | `median` | `median` `mean` `min` `max` |
| `cloud_cover_max` | number | no | `20` | 0–100 (%) |

---

## Examples

### NDVI + true color, summer composite (farm by ID)

```bash
curl -s -X POST http://<host>:5000/processes/sentinel-fetch/execution \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {
      "farm_id": 4,
      "temporal_extent": ["2024-06-01", "2024-08-31"],
      "output_products": ["ndvi", "true_color"],
      "aggregation_method": "median",
      "cloud_cover_max": 20
    }
  }' | python3 -m json.tool
```

### All vegetation indices, strict cloud filter

```bash
curl -s -X POST http://<host>:5000/processes/sentinel-fetch/execution \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {
      "farm_id": 75,
      "temporal_extent": ["2024-06-01", "2024-08-31"],
      "output_products": ["ndvi", "evi", "savi"],
      "aggregation_method": "max",
      "cloud_cover_max": 15
    }
  }' | python3 -m json.tool
```

### Max-NDVI growing season (peak greenness)

```bash
curl -s -X POST http://<host>:5000/processes/sentinel-fetch/execution \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {
      "farm_id": 27,
      "temporal_extent": ["2024-05-01", "2024-09-30"],
      "output_products": ["ndvi"],
      "aggregation_method": "max",
      "cloud_cover_max": 20
    }
  }' | python3 -m json.tool
```

### Raw bands via explicit polygon geometry

```bash
curl -s -X POST http://<host>:5000/processes/sentinel-fetch/execution \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {
      "farm_geometry": {
        "type": "Polygon",
        "coordinates": [[
          [-71.5, 45.5], [-71.4, 45.5], [-71.4, 45.6],
          [-71.5, 45.6], [-71.5, 45.5]
        ]]
      },
      "temporal_extent": ["2024-07-01", "2024-07-31"],
      "output_products": ["ndvi", "evi", "true_color"],
      "aggregation_method": "median",
      "cloud_cover_max": 15
    }
  }' | python3 -m json.tool
```

---

## Response

```json
{
  "id": "result",
  "value": {
    "stac_item_id": "sentinel2_farm_4_2024-06-01_2024-08-31",
    "assets": {
      "ndvi": {
        "href": "/data/sentinel2_farm_4_ndvi_2024-06-01_2024-08-31_a1b2c3d4.tif",
        "type": "image/tiff; application=geotiff"
      },
      "true_color": {
        "href": "/data/sentinel2_farm_4_true_color_2024-06-01_2024-08-31_e5f6g7h8.tif",
        "type": "image/tiff; application=geotiff"
      }
    },
    "preview_url": "http://<host>:8082/cog/preview.png?url=/data/sentinel2_farm_4_ndvi_...tif&rescale=0,1",
    "bbox": [-71.5, 45.5, -71.4, 45.6],
    "temporal_extent": ["2024-06-01", "2024-08-31"],
    "area_km2": 98.5
  }
}
```

---

## Data storage

| Location | Content |
| --- | --- |
| `/data/output/raster_cog/` | COG files |
| `pgstac.collections` → `sentinel2_eo_products` | STAC metadata |
| `public.sentinel2_products` | Product metadata table |

### Viewing results

```bash
# TiTiler preview
http://<host>:8082/cog/preview.png?url=/data/{filename}&rescale=0,1

# STAC Browser
http://<host>:8085
```

---

## Caveats

| Item | Detail |
| --- | --- |
| Auth token | `OPENEO_REFRESH_TOKEN` expires ~30 days. Regenerate with `scripts/get_openeo_token.sh`. |
| Sentinel-2 archive | Data starts June 2015. Requests before 2015-06-01 return no data. |
| Revisit time | ~5-day revisit. Periods shorter than 10 days may have very few or no cloud-free scenes. |
| Cloud cover | Low `cloud_cover_max` on a short period may return no valid scenes. Widen the window or raise the threshold. |
| Aggregation | `median` is recommended for vegetation indices — suppresses cloud edge artifacts better than `mean`. |
| Processing time | Fetching and processing is slow (minutes for large areas). Prefer farm-scale polygons over large bboxes. |

---

## References

- [openEO Documentation](https://openeo.org/documentation/1.0/)
- [Copernicus Data Space](https://dataspace.copernicus.eu)
- [OPENEO_SETUP.md](OPENEO_SETUP.md)
