# Data Source Catalog

Authoritative inventory of integrated data sources. This file intentionally contains only the catalog tables.

All sources are published under open-government licenses that permit commercial use with attribution: [OGL-Québec](https://www.donneesquebec.ca/licence/) (OGL-Q) and [OGL-Canada](https://open.canada.ca/en/open-government-licence-canada). Software licenses are inventoried separately in [THIRD_PARTY_LICENSES.md](../THIRD_PARTY_LICENSES.md).

## Internal Data

| Source | Type | Source Format | CRS | Last Update | Status | License | Description | Details |
| ------ | ---- | ------ | --- | ------ | ------ | ------- | ----------- | ------- |
| BDPPAD | Vector | ShapeFile (.shp) | 4326 | July 2026 | Prod | OGL-Q | Agricultural parcels and declared production data (FADQ) | [Details](sources/BDPPAD.md) |
| GRHQ | Vector | GeoPackage (.gpkg) | 4326 | July 2026 | Prod | OGL-Q | Hydrographic network - standard resolution (1:50,000) | [Details](sources/GRHQ.md) |
| GRHQ-HR | Vector | GeoPackage (.gpkg) | 4326 | July 2026 | Prod | OGL-Q | Hydrographic network - high resolution (1:20,000) | [Details](sources/GRHQ.md) |
| CARTE_PEDOLOGIQUE_QUEBEC | Vector | ShapeFile (.shp) | 4326 | July 2026 | Prod | OGL-Q | Pedological soil maps with classification and properties (IRDA) | [Details](sources/CARTE_PEDOLOGIQUE_QUEBEC.md) |
| SIIGSOL-100m | Raster | GeoTIFF (.tif) | 4326 | July 2026 | Prod | OGL-Q | Provincial soil properties grid at 100m resolution (MAPAQ) | [Details](sources/SIIGSOL.md) |
| SERIES_SOLS_QUEBEC | Vector | CSV (linked tables) | N/A | July 2026 | Prod | OGL-Q | Relational soil series data with properties, textures, and organic matter studies linked to pedological maps (IRDA) | [Details](sources/SERIES_SOLS_QUEBEC.md) |

## Open API Data (External)

Datasets fetched on demand from external open APIs — by the process-api processes or the map frontend — not ingested by the pipeline. All licenses permit commercial use with attribution.

| Source | Fetched by | Provider | License | Description | Details |
| ------ | ---------- | -------- | ------- | ----------- | ------- |
| AAC_ANNUAL_CROP | map frontend (`/aac-identify/` proxy) | Agriculture and Agri-Food Canada | OGL-Canada | Annual crop classification raster for Canada 2016–2024 | [Details](sources/AAC_ANNUAL_CROP.md) |
| Sentinel-2 L2A | `sentinel-fetch` | Copernicus Data Space (ESA) | [Copernicus Sentinel licence](https://sentinels.copernicus.eu/documents/247904/690755/Sentinel_Data_Legal_Notice) | Satellite imagery → vegetation indices (NDVI, EVI, SAVI) | [Specs](../../process-api/docs/SENTINEL_FETCH_PROCESS.md) |
| Quebec LiDAR derivatives | `lidar-fetch` | MRNF, Gouvernement du Québec | OGL-Canada 2.0 | DTM, CHM, hillshade, slope rasters (1–2 m) | [Specs](../../process-api/docs/LIDAR_QUERY_SPECS.md) |
| ERA5-Land | `weather-timeseries`, `climate-indicators` | Copernicus C3S via PAVICS (Ouranos) | [Copernicus C3S licence](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land) | Historical reanalysis, daily/hourly, 1950 → present | [Specs](../../process-api/docs/CLIMATE_WEATHER_SPECS.md) |
| RDRS v2.1 | `weather-timeseries`, `climate-indicators` | ECCC via PAVICS (Ouranos) | ECCC open data | Regional reanalysis, 1980–2018 | [Specs](../../process-api/docs/CLIMATE_WEATHER_SPECS.md) |
| CMIP6 ESPO-G6-R2 | `climate-timeseries`, `climate-indicators` | Ouranos via PAVICS | CC-BY 4.0 | Bias-adjusted climate projections, 26 models, 1950–2100 | [Specs](../../process-api/docs/CLIMATE_WEATHER_SPECS.md) |
| MSC GeoMet observations | `msc-observations` | Environment and Climate Change Canada | [ECCC Data Servers End-use Licence](https://eccc-msc.github.io/open-data/licence/readme_en/) | Weather station observations (climate-daily, SWOB real-time) | [Specs](../../process-api/docs/MSC_OBSERVATIONS_QUERY_SPECS.md) |
