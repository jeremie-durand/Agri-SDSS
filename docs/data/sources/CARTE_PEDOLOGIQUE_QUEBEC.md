# Cartes pédologiques du Québec (IRDA)

Pedological soil maps for Quebec published by IRDA, providing detailed soil polygon mapping and attributes.

## Overview

**Cartes pédologiques du Québec** deliver polygon soil units with classification, texture, drainage, and slope information to support agronomy and land evaluation.
Source: IRDA (Institut de recherche et de développement en agroenvironnement).

## Data Details

| Property | Value |
|----------|-------|
| **Type** | Vector (polygons) |
| **Format** | Shapefile (.shp) |
| **CRS** | Harmonized to EPSG:4326 (WGS84) in pipeline *(source CRS may differ)* |
| **Resolution / Scale** | Map scale ~1:20,000 to 1:50,000 (pedological survey scale) |
| **Spatial Extent** | Quebec province (coverage varies by survey area) |
| **Update Frequency** | Occasional / static releases |
| **License** | Open Government License - Quebec (OGL-Q) |
| **Source URL** | https://irda.qc.ca/fr/outils/donnees-pedologiques-sols/cartes-pedologiques-quebec-irda/ |

## Using the Data

- Identify soil suitability for crops (combine with SIIGSOL and BDPPAD)
- Overlay with parcels for management zones
- Drainage and erosion risk assessment
- Land evaluation for infrastructure planning

## Integration Notes

- Input as polygon vector; CRS normalized to EPSG:4326 during ingestion.
- Ensure attribute mappings for soil unit codes and texture/drainage classes.
- Apply spatial indexes in PostGIS (BRIN/GIST) after import.
- Consider dissolving by soil unit for summary layers.

## Metadata

- **Publisher**: IRDA (Institut de recherche et de développement en agroenvironnement)
- **External Link**: https://irda.qc.ca/fr/outils/donnees-pedologiques-sols/cartes-pedologiques-quebec-irda/
