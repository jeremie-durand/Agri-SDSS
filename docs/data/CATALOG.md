# Data Source Catalog

Authoritative inventory of integrated data sources. This file intentionally contains only the catalog table. For usage guides and implementation details, see docs/data/README.md and per-source pages.

## Master Table

| Source | Type | Source Format | CRS | Last Update | Status | Description | Details |
|--------|------|--------|-----|--------|--------|-------------|---------|
| BDPPAD | Vector | ShapeFile (.shp) | 4326 | December 2025 | Dev | Agricultural parcels and declared production data (FADQ) | [Link](sources/BDPPAD.md) |
| GRHQ | Vector | GeoPackage (.gpkg) | 4326 | December 2025 | Dev | Hydrographic network - standard resolution (1:50,000) | [Link](sources/GRHQ.md) |
| GRHQ-HR | Vector | GeoPackage (.gpkg) | 4326 | December 2025 | Dev | Hydrographic network - high resolution (1:20,000) | [Link](sources/GRHQ.md) |
| CARTE_PEDOLOGIQUE_QUEBEC | Vector | ShapeFile (.shp) | 4326 | December 2025 | Dev | Pedological soil maps with classification and properties (IRDA) | [Link](sources/CARTE_PEDOLOGIQUE_QUEBEC.md) |
| SIIGSOL-100m | Raster | GeoTIFF (.tif) | 4326 | December 2025 | Dev | Provincial soil properties grid at 100m resolution (MAPAQ) | [Link](sources/SIIGSOL.md) |

Notes:
- The Details column links to per-source documentation under docs/data/sources/.
