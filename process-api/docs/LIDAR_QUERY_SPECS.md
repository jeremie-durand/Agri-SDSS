# Quebec LiDAR Query Specifications

## Overview

The `lidar-fetch` OGC Process fetches LiDAR-derived raster products from the Quebec
MRNF open data portal for a given farm polygon. Tiles covering the farm's bounding box
are downloaded, mosaicked if needed, clipped to the farm extent, converted to Cloud
Optimized GeoTIFF (COG), and published to the STAC catalog.

**Data source:** [Produits dérivés de base du LiDAR — Données Québec](https://www.donneesquebec.ca/recherche/dataset/produits-derives-de-base-du-lidar)
**Publisher:** Ministère des Ressources naturelles et des Forêts (MRNF), Gouvernement du Québec
**License:** Open Government Licence – Canada 2.0

---

## Tile Index

The process resolves farm geometries to tile download URLs using the MRNF's publicly
available tile index GeoJSON:

```text
https://diffusion.mffp.gouv.qc.ca/Diffusion/DonneeGratuite/Foret/IMAGERIE/
Produits_derives_LiDAR/Produit_derive_lidar/03-Telechargement/URL_Lidar.geojson
```

- **2,630 tiles** covering the surveyed portions of Quebec
- Each tile is approximately **15 km × 15 km**
- Tile geometries are in **EPSG:4326**
- The index is cached locally at `/tmp/quebec_lidar_tile_index.geojson` (TTL: 24 h)

---

## Product Catalogue

| Product key | MRNF column | Description | Resolution | Unit |
| ------------- | ------------- | ------------- | ----------- | ------ |
| `dtm` | `MNT` | Digital Terrain Model — bare ground elevation | 1 m | metres ASL |
| `chm` | `MHC` | Canopy Height Model — vegetation height (DSM − DTM) | 1 m | metres |
| `hillshade` | `MNT_Ombre` | Shaded relief derived from DTM | 2 m | — |
| `slope` | `Pentes` | Slope gradient derived from DTM | 2 m | degrees, percent |
| `aspect` | *(derived)* | Downslope compass bearing, derived locally from DTM via `gdaldem aspect` — not an MRNF product | 1 m | degrees (0=North) |

> **Note:** The MRNF dataset does not include a Digital Surface Model (DSM) or aspect
> raster as standalone products. The CHM implicitly encodes the DSM−DTM difference.
> `aspect` is computed on demand from the fetched DTM; requesting it also fetches DTM
> internally even if `dtm` is not itself in `products`.

### Statistics

`dtm`, `chm`, and `hillshade` statistics are a **bounding-box mean** (the COG's full
extent, i.e. the farm's rectangular bounding box). `slope` and `aspect` statistics are
computed over the **exact farm polygon** (pixels outside the polygon, and nodata
pixels, are excluded). `slope`'s percent value is the average of the per-pixel percent
conversion (`tan(radians(degrees)) * 100`), not a conversion of the mean degrees value.
`aspect`'s mean is a circular mean (vector average), since aspect wraps at 360/0 degrees.

### Agricultural relevance

| Product | Precision agriculture use case |
| --------- | ------------------------------- |
| `dtm` | Drainage modelling, water flow, soil depth proxies |
| `chm` | Crop height monitoring, hedgerow/windbreak mapping |
| `hillshade` | Visual interpretation, slope aspect proxy |
| `slope` | Erosion risk, tillage constraints, equipment access |
| `aspect` | Solar exposure, frost-pocket risk, crop/orientation planning |

---

## Process Inputs

| Input | Type | Required | Default | Description |
| ------- | ------ | ---------- | --------- | ------------- |
| `farm_id` | integer | one of | — | PostGIS row ID; queries `FARM_TABLE_NAME` |
| `farm_geometry` | GeoJSON | one of | — | Polygon or MultiPolygon in EPSG:4326 |
| `products` | array of strings | no | dtm, chm, hillshade, slope | Subset of `["dtm","chm","hillshade","slope","aspect"]`. Requesting `aspect` also fetches `dtm` internally. |

Exactly one of `farm_id` or `farm_geometry` must be provided.

**Area limit:** 200 km². Requests exceeding this threshold return a `ProcessorExecuteError`.

---

## Process Outputs

```json
{
  "stac_items": [
    "lidar_dtm_farm_4_abc123",
    "lidar_slope_farm_4_def456",
    "lidar_aspect_farm_4_ghi789"
  ],
  "assets": {
    "dtm": {
      "href": "/data/lidar_dtm_farm_4_abc123.tif",
      "type": "image/tiff; application=geotiff; profile=cloud-optimized",
      "title": "Digital Terrain Model (DTM)",
      "roles": ["data"],
      "statistics": { "mean": 312.4 }
    },
    "slope": {
      "href": "/data/lidar_slope_farm_4_def456.tif",
      "type": "image/tiff; application=geotiff; profile=cloud-optimized",
      "title": "Slope (degrees and percent)",
      "roles": ["data"],
      "statistics": { "mean_degrees": 4.2, "mean_percent": 7.3 }
    },
    "aspect": {
      "href": "/data/lidar_aspect_farm_4_ghi789.tif",
      "type": "image/tiff; application=geotiff; profile=cloud-optimized",
      "title": "Aspect (compass bearing, degrees)",
      "roles": ["data"],
      "statistics": { "mean_degrees": 187.5 }
    }
  },
  "bbox": [-72.05, 45.30, -71.95, 45.40],
  "products": ["dtm", "slope", "aspect"],
  "slope": { "mean_degrees": 4.2, "mean_percent": 7.3 },
  "aspect": { "mean_degrees": 187.5 }
}
```

---

## COG Output Specifications

| Setting | Value |
| --------- | ------- |
| Format | Cloud Optimized GeoTIFF (`-of COG`) |
| Compression | DEFLATE |
| Block size | 512 × 512 px |
| Overviews | AUTO |
| CRS | EPSG:4326 |
| Nodata | −9999 |
| Clipping | Farm bounding box (`-te` passed to `gdalwarp`) |

---

## STAC Collection

- **Collection ID:** `lidar_quebec`
- **STAC version:** 1.0.0
- **Extensions:** `projection/v1.0.0`, `raster/v1.1.0`
- **Spatial extent:** Quebec province (−79.75, 41.75, −56.0, 63.0)
- **Temporal extent:** 2015-01-01 / open

One STAC item is published per product per request. Re-running the process for the
same farm updates the existing STAC items (HTTP PUT on 409 Conflict).

### STAC item properties

| Property | Value |
| ---------- | ------- |
| `platform` | `lidar-mrnf` |
| `instruments` | `["lidar"]` |
| `lidar:product` | product key (e.g. `dtm`) |
| `lidar:source` | `MRNF Quebec open data` |
| `proj:epsg` | `4326` |

---

## Accessing Results

### STAC API

```bash
# List all LiDAR items
curl http://<host>:8081/collections/lidar_quebec/items

# Get a specific item
curl http://<host>:8081/collections/lidar_quebec/items/lidar_dtm_farm_4_abc123
```

### Raster API

LiDAR COGs are registered as STAC assets and can be served as map tiles or inspected via the raster-api (port 8082):

```bash
# Tile endpoint (use in Leaflet/MapLibre as XYZ source)
http://<host>:8082/cog/tiles/{z}/{x}/{y}?url=<cog_asset_href>

# File info (band count, CRS, nodata, bounds)
curl "http://<host>:8082/cog/info?url=<cog_asset_href>"

# Band statistics (min, max, mean, std)
curl "http://<host>:8082/cog/statistics?url=<cog_asset_href>"
```

---

## Coverage

Not all of Quebec has been surveyed. The process raises `ProcessorExecuteError` with
message `"No LiDAR tiles found for the supplied geometry"` when the farm falls outside
the surveyed area. Coverage can be inspected visually at:
<https://lidar-telechargement.portailcartographique.gouv.qc.ca/>
