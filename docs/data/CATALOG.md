# Data Source Catalog

Authoritative inventory of integrated data sources. This file intentionally contains only the catalog tables.

Each source keeps its publisher's license, given in the License column. Données Québec publishes under [CC BY 4.0](https://www.donneesquebec.ca/licence/#cc-by), which permits commercial use with attribution. IRDA's pedological data (maps and soil series) is under [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/): non-commercial use only ([IRDA user guide, §2.3](https://irda.qc.ca/media/kd2gfs4w/irda-donneesgeospatialescouverturepedologiquequebec-guide-mars2026.pdf)). Federal sources use [OGL-Canada](https://open.canada.ca/en/open-government-licence-canada) or the ECCC Data Servers End-use Licence. Software licenses are inventoried separately in [THIRD_PARTY_LICENSES.md](../THIRD_PARTY_LICENSES.md).

The frontend `/data` page renders from [frontend/home/html/js/catalog.json](../../frontend/home/html/js/catalog.json) joined with the live API collection lists — update that file (entry + `match` pattern) whenever a source is added or renamed here. Ingested collections matching no entry appear automatically under "Other datasets in the backend".

## Internal Data

| Source | Type | Source Format | CRS | Last Update | Status | License | Description | Details |
| ------ | ---- | ------ | --- | ------ | ------ | ------- | ----------- | ------- |
| BDPPAD | Vector | ShapeFile (.shp) | 4326 | July 2026 | Prod | CC BY 4.0 | Agricultural parcels and declared production data (FADQ) | [Details](sources/BDPPAD.md) |
| GRHQ | Vector | GeoPackage (.gpkg) | 4326 | July 2026 | Prod | CC BY 4.0 | Hydrographic network - standard resolution (1:50,000) | [Details](sources/GRHQ.md) |
| GRHQ-HR | Vector | GeoPackage (.gpkg) | 4326 | July 2026 | Prod | CC BY 4.0 | Hydrographic network - high resolution (1:20,000) | [Details](sources/GRHQ.md) |
| CARTE_PEDOLOGIQUE_QUEBEC | Vector | ShapeFile (.shp) | 4326 | July 2026 | Prod | CC BY-NC 4.0 | Pedological soil maps with classification and properties (IRDA) | [Details](sources/CARTE_PEDOLOGIQUE_QUEBEC.md) |
| SIIGSOL-100m | Raster | GeoTIFF (.tif) | 4326 | July 2026 | Prod | CC BY 4.0 | Provincial soil properties grid at 100m resolution (MAPAQ) | [Details](sources/SIIGSOL.md) |
| SERIES_SOLS_QUEBEC | Vector | CSV (linked tables) | N/A | July 2026 | Prod | CC BY-NC 4.0 | Relational soil series data with properties, textures, and organic matter studies linked to pedological maps (IRDA) | [Details](sources/SERIES_SOLS_QUEBEC.md) |

A demo extract of BDPPAD (Les Maskoutains area, 2025, ~14,500 parcels, ~11 MB) is committed at `data/demo/bdppad/` so fresh installs can seed the map — see the README [Quick start](../../README.md#load-the-demo-data). It was built on 2026-07-17 from `BDPPAD_v03_AN_2025_s_20260713.shp` by selecting parcels intersecting bbox `(-73.2, 45.45, -72.7, 45.8)` (EPSG:4269) with geopandas; to regenerate for a new year, apply the same filter and name the file `bdppad_demo_an_<year>.gpkg` — the filename stem becomes the PostGIS table name and drives the year label in the map's BDPPAD panel. If you later ingest the full BDPPAD year, drop the demo table first (`DROP TABLE public.bdppad_demo_an_2025;`) to avoid two "2025" entries.

## Open API Data (External)

Datasets fetched on demand from external open APIs — by the process-api processes or the map frontend — not ingested by the pipeline. All licenses permit commercial use with attribution.

| Source | Fetched by | Provider | License | Description | Details |
| ------ | ---------- | -------- | ------- | ----------- | ------- |
| AAC_ANNUAL_CROP | map frontend (`/aac-identify/` proxy) | Agriculture and Agri-Food Canada | OGL-Canada | Annual crop classification raster for Canada 2016–2025 | [Details](sources/AAC_ANNUAL_CROP.md) |
| Sentinel-2 L2A | `sentinel-fetch` | Copernicus Data Space (ESA) | [Copernicus Sentinel licence](https://sentinels.copernicus.eu/documents/247904/690755/Sentinel_Data_Legal_Notice) | Satellite imagery → vegetation indices (NDVI, EVI, SAVI) | [Specs](../../process-api/docs/SENTINEL_FETCH_PROCESS.md) |
| Quebec LiDAR derivatives | `lidar-fetch` | MRNF, Gouvernement du Québec | [CC BY 4.0](https://www.donneesquebec.ca/licence/#cc-by) | DTM, CHM, hillshade, slope rasters (1–2 m) | [Specs](../../process-api/docs/LIDAR_QUERY_SPECS.md) |
| ERA5-Land | `weather-timeseries`, `climate-indicators` | Copernicus C3S via PAVICS (Ouranos) | [CC BY 4.0](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land) | Historical reanalysis, daily/hourly, 1950 → present | [Specs](../../process-api/docs/CLIMATE_WEATHER_SPECS.md) |
| RDRS v2.1 | `weather-timeseries`, `climate-indicators` | ECCC via PAVICS (Ouranos) | [ECCC Data Servers End-use Licence](https://eccc-msc.github.io/open-data/licence/readme_en/) | Regional reanalysis, 1980–2018 | [Specs](../../process-api/docs/CLIMATE_WEATHER_SPECS.md) |
| CMIP6 ESPO-G6-R2 | `climate-timeseries`, `climate-indicators` | Ouranos via PAVICS | CC BY 4.0 | Bias-adjusted climate projections, 26 models, 1950–2100 | [Specs](../../process-api/docs/CLIMATE_WEATHER_SPECS.md) |
| MSC GeoMet observations | `msc-observations` | Environment and Climate Change Canada | [ECCC Data Servers End-use Licence](https://eccc-msc.github.io/open-data/licence/readme_en/) | Weather station observations (climate-daily, SWOB real-time) | [Specs](../../process-api/docs/MSC_OBSERVATIONS_QUERY_SPECS.md) |
