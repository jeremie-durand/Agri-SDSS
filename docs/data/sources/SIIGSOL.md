# SIIGSOL - Soil Properties Grid (100m)

Provincial soil properties coverage at 100-meter resolution from the Système d'Information Informatisé sur les Propriétés du Sol.

## Overview

**SIIGSOL-100m** is Quebec's comprehensive soil properties dataset providing gridded (raster) information about soil composition, chemistry, and physical properties at 100-meter resolution across the entire province.

Maintained by Ministère de l'Agriculture, des Pêcheries et de l'Alimentation du Québec (MAPAQ).

## Data Details

| Property | Value |
| -------- | ----- |
| **Type** | Raster (one single-property COG per soil property) |
| **Format** | Cloud Optimized GeoTIFF (.tif) |
| **CRS** | EPSG:4326 (WGS84) |
| **Resolution** | 100m × 100m grid cells |
| **Spatial Extent** | Quebec province |
| **Band Count** | 7 per file (bands 1–6: property values, band 7: alpha mask) |
| **Data Type** | Float32 |
| **Update Frequency** | Annual |
| **License** | Open Government License - Quebec (OGL-Q) |

## Property Files

Each soil property is a separate COG in `data/output/raster_cog/`:

| File | Property | Unit | Range |
| ---- | -------- | ---- | ----- |
| `argile_fr_siigsol_cog.tif` | Clay (argile) | % | 0-100 |
| `limon_fr_siigsol_cog.tif` | Silt (limon) | % | 0-100 |
| `sable_fr_siigsol_cog.tif` | Sand (sable) | % | 0-100 |
| `corg_fr_siigsol_cog.tif` | Organic carbon (C org) | % | 0-15 |
| `ph_fr_siigsol_cog.tif` | pH | pH units | 3.5-8.5 |
| `cec_fr_siigsol_cog.tif` | Cation Exchange Capacity | cmol/kg | 0-50 |

**Band layout caveat**: each COG carries a float32 alpha band as its last band and no
declared nodata value. For statistics or point queries via TiTiler, always pass
`indexes=1` and `nodata=nan` — otherwise the alpha band skews the results.

## Using SIIGSOL Data

**Note**: The following examples require services to be running (`docker compose up`).
Inside the raster-api container the COG directory is mounted at `/data`.

```bash
# COG metadata (bounds, bands, CRS)
curl "http://<host>:8082/cog/info?url=/data/ph_fr_siigsol_cog.tif"

# Band statistics — indexes=1 and nodata=nan required (alpha band)
curl "http://<host>:8082/cog/statistics?url=/data/ph_fr_siigsol_cog.tif&indexes=1&nodata=nan"

# PNG tile (organic carbon, rescaled for display)
curl "http://<host>:8082/cog/tiles/10/302/368.png?url=/data/corg_fr_siigsol_cog.tif&indexes=1&nodata=nan&rescale=0,15"
```

## Metadata

- **Publisher**: Ministère de l'Agriculture, des Pêcheries et de l'Alimentation du Québec (MAPAQ)
- **Language**: French
- **External Links**:
  - Données Québec: https://www.donneesquebec.ca/recherche/dataset/siigsol-100m-carte-des-proprietes-du-sol
  - MAPAQ Portal: https://www.mapaq.gouv.qc.ca/fr/Pages/Accueil.aspx
