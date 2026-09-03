# GRHQ - Géobase du Réseau Hydrographique du Québec

Hydrographic network data for Quebec including water features, watercourses, and water bodies.

## Overview

**GRHQ** provides a comprehensive vector dataset of Quebec's hydrographic network maintained by the Government of Quebec (Ministère de l'Environnement, de la Lutte contre les Changements Climatiques et de la Prévention des Incendies de Forêt - MELCCFP).

Two versions are available:

- **Standard GRHQ**: 1:50,000 resolution, complete coverage
- **GRHQ-HR** (High Resolution): 1:20,000 resolution, ongoing development

## Data Details

| Property | Value |
| ---------- | ------- |
| **Type** | Vector (polylines, polygons, multipart geometries) |
| **Format** | GeoPackage (.gpkg), Shapefile (.shp) |
| **CRS** | EPSG:4326 (WGS84) |
| **Resolution** | Standard: 1:50,000 / HR: 1:20,000 |
| **Spatial Extent** | Quebec province |
| **Update Frequency** | Periodic (quarterly/annually) |
| **License** | Open Government License - Quebec (OGL-Q) |

## Features Included

The dataset includes:

- **Watercourses** (polylines)
  - Rivers, streams, brooks
  - Direction flow attributes
  - Classification by order and type

- **Water Bodies** (polygons)
  - Lakes, reservoirs, ponds
  - Size and area attributes
  - Seasonal vs. permanent indicators

- **Attributes**
  - Hydrographic codes
  - Feature names
  - Flow direction
  - Feature classification
  - Temporal metadata

## Using GRHQ Data

- List watercourses within a bounding box via Vector API
- Find water bodies near coordinates using STAC Search
- Filter by feature type, name, or hydrographic code
- Run spatial intersects/within queries in PostGIS
- Aggregate lengths/areas by municipality or watershed
- Overlay with SIIGSOL/BDPPAD for agronomic analysis

## GRHQ vs GRHQ-HR

| Aspect | Standard GRHQ | GRHQ-HR |
| -------- | -------------- | --------- |
| **Resolution** | 1:50,000 | 1:20,000 |
| **Completeness** | 100% | ~85% (ongoing) |
| **Accuracy** | High | Very High |
| **File Size** | Smaller (~500MB) | Larger (~800MB) |
| **Update Status** | Stable | Active development |
| **Recommendation** | Default choice | Use when available |

**Pipeline Behavior:**
The gis-pipeline checks for GRHQ-HR first and automatically falls back to standard GRHQ if HR version is unavailable.

## Metadata

- **Publisher**: Government of Quebec (MELCCFP)
- **Language**: French/English
- **External Links**:
  - Standard: <https://www.donneesquebec.ca/recherche/dataset/grhq>
  - High Resolution: <https://www.donneesquebec.ca/recherche/dataset/geobase-du-reseau-hydrographique-du-quebec-a-haute-resolution-grhq-hr>
