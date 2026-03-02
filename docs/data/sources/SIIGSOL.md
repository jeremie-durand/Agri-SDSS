# SIIGSOL - Soil Properties Grid (100m)

Provincial soil properties coverage at 100-meter resolution from the Système d'Information Informatisé sur les Propriétés du Sol.

## Overview

**SIIGSOL-100m** is Quebec's comprehensive soil properties dataset providing gridded (raster) information about soil composition, chemistry, and physical properties at 100-meter resolution across the entire province.

Maintained by Ministère de l'Agriculture, des Pêcheries et de l'Alimentation du Québec (MAPAQ).

## Data Details

| Property | Value |
|----------|-------|
| **Type** | Raster (multi-band GeoTIFF) |
| **Format** | GeoTIFF (.tif), Cloud Optimized GeoTIFF (.cog.tif) |
| **CRS** | EPSG:4326 (WGS84) |
| **Resolution** | 100m × 100m grid cells |
| **Spatial Extent** | Quebec province |
| **Band Count** | 6 main properties + derivatives |
| **Data Type** | Float32 (percentages, pH, indices) |
| **Update Frequency** | Annual |
| **License** | Open Government License - Quebec (OGL-Q) |

## Soil Properties (Bands)

Each band contains a specific soil property:

| Band | Property | Unit | Range | Interpretation |
|------|----------|------|-------|-----------------|
| **1** | Clay | % | 0-100 | Percentage of clay particles (<2µm) |
| **2** | Silt | % | 0-100 | Percentage of silt particles (2-63µm) |
| **3** | Sand | % | 0-100 | Percentage of sand particles (>63µm) |
| **4** | Organic Matter (C_org) | % | 0-15 | Soil carbon content, critical for fertility |
| **5** | pH | pH units | 3.5-8.5 | Soil acidity/basicity, affects nutrient availability |
| **6** | Cation Exchange Capacity (CEC) | cmol/kg | 0-50 | Soil capacity to hold nutrients |

## Using SIIGSOL Data

**Note**: The following examples require services to be running (`docker compose up`).

- Visualize in browser: http://localhost:8082/preview?url=data/siigsol_organic_matter.cog.tif
- Fetch a PNG tile (z10/x512/y512, Organic Matter): curl "http://localhost:8082/cog/tiles/10/512/512.png?url=data/siigsol_corg.cog.tif"
- Request GeoTIFF coverage (WCS, EPSG:4326 bbox): curl "http://localhost:8082/cog/wcs?service=WCS&request=GetCoverage&coverageId=siigsol&format=image/tiff&bbox=-71.5,45.0,-71.0,45.5&crs=EPSG:4326"

## Metadata

- **Publisher**: Ministère de l'Agriculture, des Pêcheries et de l'Alimentation du Québec (MAPAQ)
- **Language**: French
- **External Links**:
  - Données Québec: https://www.donneesquebec.ca/recherche/dataset/siigsol-100m-carte-des-proprietes-du-sol
  - MAPAQ Portal: https://www.mapaq.gouv.qc.ca/fr/Pages/Accueil.aspx
