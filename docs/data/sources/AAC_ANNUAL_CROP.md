# AAC Annual Crop Inventory

Annual raster crop classification for Canada published by Agriculture and Agri-Food Canada (AAC).

## Overview

**Annual Crop Inventory** provides a pixel-level crop type classification across Canada derived from satellite imagery. Used in the MOS-GIS map for crop identification by clicking a location.

## Data Details

| Property | Value |
|----------|-------|
| **Type** | Raster (ImageServer) |
| **Format** | ArcGIS REST ImageServer (streamed — not ingested locally) |
| **CRS** | Web Mercator (EPSG:3857) |
| **Resolution** | 30m |
| **Spatial Extent** | Canada |
| **Years available** | 2016 – 2024 (2025 not yet live) |
| **Update Frequency** | Annual |
| **License** | Open Government Licence - Canada |
| **Source URL** | https://agriculture.canada.ca/imagery-images/rest/services/inventaire_annuel_des_cultures/ |

## Integration

This dataset is **not ingested** by the pipeline — it is fetched live from the AAC ArcGIS REST ImageServer at render time.

- **Tile rendering**: `https://agriculture.canada.ca/imagery-images/rest/services/inventaire_annuel_des_cultures/{year}/ImageServer/exportImage` — proxied via `/aac-identify/` (nginx CORS proxy) and rendered as a Leaflet image overlay.
- **Identify on click**: `/aac-identify/inventaire_annuel_des_cultures/{year}/ImageServer/identify` returns the crop code at a clicked location; decoded using `aac-crop-codes.js`.
- **Frontend module**: `frontend/home/html/js/aac.js`

## Metadata

- **Publisher**: Agriculture and Agri-Food Canada (AAC / AAC)
- **External Link**: https://open.canada.ca/data/en/dataset/ba2645d5-4458-414d-b196-6303ac06c1c9
