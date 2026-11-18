# process-api

OGC API Processes service built on PyGeoAPI. Executes server-side geospatial processes: satellite imagery retrieval, LiDAR products, climate/weather timeseries, agronomic indicators, and soil organic matter prediction.

**Port**: 5000 | **Requires**: `OPENEO_REFRESH_TOKEN` for Sentinel processes (expires ~30 days)

Interactive API docs: `http://<host>/process-api/openapi?f=html`

## Start

```bash
docker compose up -d process-api process-worker
docker compose restart home
```

`process-worker` runs the async jobs (see below). It uses the same image with
`python -m processes.worker` as its command, so rebuild both after a change to
`processes/`.

```bash
docker compose up -d --build process-api process-worker   # after a code change
docker compose up -d --scale process-worker=2             # two jobs at a time
docker compose logs -f process-worker                     # "ready", claimed, finished
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
| `water-distance` | Geodesic distance from a parcel to the nearest GRHQ water feature |
| `som-field-match` | SOM field boundaries near a parcel, GEE-positive fields first |
| `pedo-coverage` | Pedological classes covering a parcel (IRDA 2026, falling back to 2022) |

## Execute a process

process-api is reached through the single public origin at `https://<host>/process-api/`.
Against a local deployment add `-k` (`curl -k https://localhost/...`) — the certificate is
self-signed.

```bash
curl -X POST https://<host>/process-api/processes/weather-timeseries/execution \
  -H "Content-Type: application/json" \
  -d '{"inputs": {"bbox": [-72.5, 45.3, -72.0, 45.7], "start_date": "2023-01-01", "end_date": "2023-12-31"}}'
```

### Long processes as async jobs

`sentinel-fetch`, `lidar-fetch` and `som-predict-soil` also run as jobs on the
`process-worker` service. Send `Prefer: respond-async`: the answer is `201` with a
`Location` header naming the job, and the HTTP request returns at once. Poll the
job until its `status` is `successful` or `failed`, then read the results, which
are the same body a synchronous execution returns. Other processes ignore the
header and answer synchronously.

```bash
curl -si -X POST https://<host>/process-api/processes/lidar-fetch/execution \
  -H "Content-Type: application/json" -H "Prefer: respond-async" \
  -d '{"inputs": {"farm_geometry": {"type": "Polygon", "coordinates": [[[-72.1, 45.4], [-72.0, 45.4], [-72.0, 45.5], [-72.1, 45.5], [-72.1, 45.4]]]}, "products": ["dtm"]}}' \
  | grep -i '^location'
# location: https://<host>/process-api/jobs/<job-id>

curl https://<host>/process-api/jobs/<job-id>?f=json           # accepted → running → successful | failed
curl https://<host>/process-api/jobs/<job-id>/results?f=json   # once successful
```

A failed job carries the error in its `message`, in the language of the
submitting request. Finished jobs are deleted after `PROCESS_JOB_RETENTION_DAYS`.

The job id is the only key to a job: the public origin does not list jobs
(`/process-api/jobs` answers `404`) and rejects `DELETE` (`405`). Keep the
`Location` URL to follow a job. Synchronous executions are not recorded as
jobs and their answers carry no `Location`. Inside the Docker network,
`http://process-api:5000/jobs` still lists every job (`limit`, `offset`,
newest first).

## Language

Process titles, descriptions and error messages are returned in **French by default**. Request
English with a header or pygeoapi's `lang` parameter:

```bash
curl '.../processes/msc-observations?f=json&lang=en'
curl -H "Accept-Language: en" .../processes/msc-observations?f=json
```

See [Internationalization](../docs/I18N.md).

## Configuration

`process-api/config/pygeoapi-config.yaml` — processes and providers  
`OPENEO_REFRESH_TOKEN` — Copernicus OIDC token  
`PROCESS_JOB_TIMEOUT_SECONDS` (1800), `PROCESS_JOB_RETENTION_DAYS` (7),
`PROCESS_WORKER_POLL_SECONDS` (5), `PROCESS_WORKER_SWEEP_SECONDS` (60) — async
job time budget, retention, and worker polling and sweep intervals

## Docs

→ [OpenEO token setup](docs/OPENEO_SETUP.md)  
→ [Sentinel fetch](docs/SENTINEL_FETCH_PROCESS.md)  
→ [Climate & weather specs](docs/CLIMATE_WEATHER_SPECS.md)  
→ [LiDAR query specs](docs/LIDAR_QUERY_SPECS.md)  
→ [MSC observations](docs/MSC_OBSERVATIONS_QUERY_SPECS.md)  
→ [SOM soil prediction](docs/SOM_PREDICT_SOIL_SPECS.md)  
→ [Water distance](docs/WATER_DISTANCE_SPECS.md)  
→ [SOM field match](docs/SOM_FIELD_MATCH_SPECS.md)  
→ [Pedological coverage](docs/PEDO_COVERAGE_SPECS.md)
