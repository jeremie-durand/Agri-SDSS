# BDPPAD - Parcelles et productions agricoles déclarées

Parcels and declared agricultural production dataset for Quebec (BDPPAD) published by FADQ.

## Overview

**BDPPAD** provides polygon parcels with declared crop/production attributes across Quebec. Source: FADQ (Financière agricole du Québec).

## Data Details

| Property | Value |
| ---------- | ------- |
| **Type** | Vector (polygons) |
| **Format** | Shapefile (.shp) |
| **CRS** | Harmonized to EPSG:4326 (WGS84) in pipeline *(source CRS may differ)* |
| **Resolution / Scale** | Parcel-level geometry |
| **Spatial Extent** | Quebec province |
| **Update Frequency** | Annual (declared production campaigns) |
| **License** | Open Government License - Quebec (OGL-Q) |
| **Source URL** | <https://www.fadq.qc.ca/documents/donnees/base-de-donnees-des-parcelles-et-productions-agricoles-declarees> |

## Using BDPPAD Data

- Spatial queries by region/municipality
- Crop-type filtering and area aggregation
- Overlay with soil (SIIGSOL) or hydro (GRHQ) for agronomic analysis

## Integration Notes

- Ingestion expects vector polygons; CRS is normalized to EPSG:4326.
- Ensure attribute mapping for crop codes and campaign year during load.
- Apply spatial indexing in PostGIS (BRIN/GIST) after import.

## Metadata

- **Publisher**: Financière agricole du Québec (FADQ)
- **External Link**: <https://www.fadq.qc.ca/documents/donnees/base-de-donnees-des-parcelles-et-productions-agricoles-declarees>
