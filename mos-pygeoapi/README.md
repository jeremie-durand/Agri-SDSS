# mos-pygeoapi

OGC API Processes service built on PyGeoAPI. Executes server-side geospatial processes: satellite imagery retrieval, LiDAR products, climate/weather timeseries, agronomic indicators, and soil organic matter prediction.

**Port**: 5000 | **Requires**: `OPENEO_REFRESH_TOKEN` for Sentinel processes (expires ~30 days)

Interactive API docs: `http://<host>/mos-pygeoapi/openapi?f=html`

## Start

```bash
docker compose up -d mos-pygeoapi
```

## Available processes

| Process | Description |
| --- | --- |
| `sentinel-fetch` | Sentinel-2 vegetation indices via Copernicus OpenEO |
| `lidar-fetch` | Quebec MRNF LiDAR products (DTM, CHM, hillshade) |
| `weather-timeseries` | ERA5-Land / RDRSv2.1 daily timeseries (PAVICS/Ouranos) |
| `climate-timeseries` | CMIP6 ESPO-G6-R2 projections (26 models, 1950–2100) |
| `climate-indicators` | Agronomic indicators: GDD, frost days, heat stress, precipitation |
| `msc-observations` | MSC GeoMet climate-daily and SWOB real-time station data |
| `som-predict-soil` | Soil Organic Matter prediction for field parcels (RandomForest on GEE features) |

## Execute a process

```bash
curl -X POST http://<host>:5000/processes/weather-timeseries/execution \
  -H "Content-Type: application/json" \
  -d '{"inputs": {"bbox": [-72.5, 45.3, -72.0, 45.7], "start_date": "2023-01-01", "end_date": "2023-12-31"}}'
```

## Configuration

`mos-pygeoapi/config/pygeoapi-config.yaml` — processes and providers  
`OPENEO_REFRESH_TOKEN` — Copernicus OIDC token

## Docs

→ [OpenEO token setup](docs/OPENEO_SETUP.md)  
→ [Sentinel fetch](docs/SENTINEL_FETCH_PROCESS.md)  
→ [Climate & weather specs](docs/CLIMATE_WEATHER_SPECS.md)  
→ [LiDAR query specs](docs/LIDAR_QUERY_SPECS.md)  
→ [MSC observations](docs/MSC_OBSERVATIONS_QUERY_SPECS.md)  
→ [SOM soil prediction](docs/SOM_PREDICT_SOIL_SPECS.md)
