# Weather & Climate — Query Specifications

Three processes retrieve gridded weather and climate data via the PAVICS THREDDS (OPeNDAP) backend hosted by Ouranos. No authentication required.

| Process | Endpoint | Purpose |
| --- | --- | --- |
| `weather-timeseries` | `POST /processes/weather-timeseries/execution` | Historical reanalysis timeseries |
| `climate-timeseries` | `POST /processes/climate-timeseries/execution` | CMIP6 projection timeseries |
| `climate-indicators` | `POST /processes/climate-indicators/execution` | Agronomic indicators (GDD, frost days, …) |

> For station-based observations (MSC GeoMet), see [MSC_OBSERVATIONS_QUERY_SPECS.md](MSC_OBSERVATIONS_QUERY_SPECS.md).

---

## Datasets

| `dataset` | Period | Variables | Processes |
| --- | --- | --- | --- |
| `era5_land` | 1950-01-01 → today − 90 days | `tasmin`, `tasmax`, `tas`, `pr` | `weather-timeseries`, `climate-indicators` |
| `era5_land_hourly` | 1950-01-01 → today − 90 days | `tas`, `pr` | `weather-timeseries` |
| `rdrs_v2_1` | 1980-01-01 → 2018-12-31 | `tasmin`, `tasmax`, `tas`, `pr` | `weather-timeseries`, `climate-indicators` |
| `cmip6_espo_g6_r2` | 1950-01-01 → 2100-12-31 | `tasmin`, `tasmax`, `pr` | `climate-timeseries`, `climate-indicators` |

`tas` (mean temperature) is **not available** in ESPO-G6-R2 — use `tasmin` + `tasmax`.

Source: **[ESPO-G6-R2 v1.0.0](https://pavics.ouranos.ca/twitcher/ows/proxy/thredds/catalog/datasets/simulations/bias_adjusted/cmip6/ouranos/ESPO-G/ESPO-G6-R2v1.0.0/catalog.html)** — Ouranos bias-adjusted CMIP6 projections for North America.

---

## CMIP6 scenarios

| `scenario` | Description |
| --- | --- |
| `ssp245` | Intermediate mitigation |
| `ssp370` | High emissions, low mitigation |
| `ssp585` | Very high emissions (worst case) |

---

## CMIP6 models (26 total)

| Model | Institution | ssp245 | ssp370 | ssp585 |
| --- | --- | :---: | :---: | :---: |
| `TaiESM1` | AS-RCEC | ✓ | ✓ | ✓ |
| `BCC-CSM2-MR` | BCC | ✓ | ✓ | ✓ |
| `FGOALS-g3` | CAS | ✓ | ✓ | ✓ |
| `CanESM5` | CCCma | ✓ | ✓ | ✓ |
| `CMCC-ESM2` | CMCC | ✓ | ✓ | ✓ |
| `CNRM-CM6-1` | CNRM-CERFACS | ✓ | ✓ | ✓ |
| `CNRM-ESM2-1` | CNRM-CERFACS | ✓ | ✓ | ✓ |
| `ACCESS-CM2` | CSIRO-ARCCSS | ✓ | ✓ | ✓ |
| `ACCESS-ESM1-5` | CSIRO | ✓ | ✓ | ✓ |
| `EC-Earth3-CC` | EC-Earth-Consortium | ✓ | — | ✓ |
| `EC-Earth3-Veg` | EC-Earth-Consortium | ✓ | ✓ | ✓ |
| `EC-Earth3` | EC-Earth-Consortium | ✓ | ✓ | ✓ |
| `INM-CM4-8` | INM | ✓ | ✓ | ✓ |
| `INM-CM5-0` | INM | ✓ | ✓ | ✓ |
| `IPSL-CM6A-LR` | IPSL | ✓ | ✓ | ✓ |
| `MIROC-ES2L` | MIROC | ✓ | ✓ | ✓ |
| `MIROC6` | MIROC | ✓ | ✓ | ✓ |
| `UKESM1-0-LL` | MOHC | ✓ | ✓ | ✓ |
| `MPI-ESM1-2-HR` | MPI-M | ✓ | ✓ | ✓ |
| `MPI-ESM1-2-LR` | MPI-M | ✓ | ✓ | ✓ |
| `MRI-ESM2-0` | MRI | ✓ | ✓ | ✓ |
| `NorESM2-LM` | NCC | ✓ | ✓ | ✓ |
| `NorESM2-MM` | NCC | ✓ | ✓ | ✓ |
| `KACE-1-0-G` | NIMS-KMA | ✓ | ✓ | ✓ |
| `GFDL-ESM4` | NOAA-GFDL | ✓ | ✓ | ✓ |
| `NESM3` | NUIST | ✓ | — | ✓ |

`EC-Earth3-CC` and `NESM3` do not have an ssp370 run — use ssp245 or ssp585 for those.

---

## Location types (all processes)

| `location_type` | Required field | Example value |
| --- | --- | --- |
| `"farm_id"` | `farm_id` | `"42"` |
| `"point"` | `point` | `[-71.5, 45.5]` |
| `"bbox"` | `bbox` | `[-72.0, 45.0, -71.0, 46.0]` |
| `"polygon"` | `polygon` | GeoJSON Polygon object |

All coordinates in EPSG:4326.

---

## Process: `weather-timeseries`

Retrieves gridded reanalysis timeseries from PAVICS THREDDS (OPeNDAP).
Returns a GeoJSON Feature with a daily or monthly timeseries in its properties.

### Variables

| `variable` | `era5_land` | `era5_land_hourly` | `rdrs_v2_1` | Output unit |
| --- | :---: | :---: | :---: | --- |
| `tasmin` | ✓ | — | ✓ | °C |
| `tasmax` | ✓ | — | ✓ | °C |
| `tas` | ✓ | ✓ | ✓ | °C |
| `pr` | ✓ | ✓ | ✓ | mm/day (daily) · mm/hr (hourly) |

Multiple variables can be requested in one call. Duplicates are removed automatically.

### Parameters

| Parameter | Type | Required | Default | Constraints |
| --- | --- | --- | --- | --- |
| `location_type` | string | yes | — | see table above |
| `variables` | array | yes | — | ≥ 1 item |
| `start_date` | string | yes | — | `YYYY-MM-DD`; ≥ dataset start |
| `end_date` | string | yes | — | `YYYY-MM-DD`; ≥ start_date; ≤ dataset ceiling |
| `dataset` | string | no | `era5_land` | see datasets table |
| `aggregation` | string | no | `daily` | `daily` or `monthly` |

### Examples

**ERA5-Land daily — bbox, temperature + precipitation**

```bash
curl -s -X POST http://<host>:5000/processes/weather-timeseries/execution \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {
      "location_type": "bbox",
      "bbox": [-72.0, 45.0, -71.0, 46.0],
      "variables": ["tasmin", "tasmax", "pr"],
      "start_date": "2020-06-01",
      "end_date": "2020-08-31",
      "dataset": "era5_land"
    }
  }' | python3 -m json.tool
```

**ERA5-Land monthly — point query**

```bash
curl -s -X POST http://<host>:5000/processes/weather-timeseries/execution \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {
      "location_type": "point",
      "point": [-71.5, 45.5],
      "variables": ["tasmin", "tasmax"],
      "start_date": "2010-01-01",
      "end_date": "2020-12-31",
      "dataset": "era5_land",
      "aggregation": "monthly"
    }
  }' | python3 -m json.tool
```

**RDRS daily — farm ID, full variable set**

```bash
curl -s -X POST http://<host>:5000/processes/weather-timeseries/execution \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {
      "location_type": "farm_id",
      "farm_id": "42",
      "variables": ["tasmin", "tasmax", "tas", "pr"],
      "start_date": "2010-04-01",
      "end_date": "2010-09-30",
      "dataset": "rdrs_v2_1"
    }
  }' | python3 -m json.tool
```

**ERA5-Land hourly — precipitation at a point**

```bash
curl -s -X POST http://<host>:5000/processes/weather-timeseries/execution \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {
      "location_type": "point",
      "point": [-71.5, 45.5],
      "variables": ["pr"],
      "start_date": "2022-07-01",
      "end_date": "2022-07-31",
      "dataset": "era5_land_hourly"
    }
  }' | python3 -m json.tool
```

---

## Process: `climate-timeseries`

Retrieves daily CMIP6 projection timeseries from PAVICS THREDDS (OPeNDAP).
Returns a GeoJSON Feature with scenario and model metadata.

### Parameters

| Parameter | Type | Required | Default | Constraints |
| --- | --- | --- | --- | --- |
| `location_type` | string | yes | — | see table above |
| `variables` | array | yes | — | any of `tasmin` `tasmax` `pr`; ≥ 1 item |
| `start_date` | string | yes | — | `YYYY-MM-DD`; ≥ 1950-01-01 |
| `end_date` | string | yes | — | `YYYY-MM-DD`; ≤ 2100-12-31 |
| `dataset` | string | yes | — | `cmip6_espo_g6_r2` |
| `scenario` | string | yes | — | `ssp245` `ssp370` `ssp585` |
| `model` | string | yes | — | any model from the table above |
| `aggregation` | string | no | `daily` | `daily` or `monthly` |

### Examples

**Daily timeseries — mid-century summer**

```bash
curl -s -X POST http://<host>:5000/processes/climate-timeseries/execution \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {
      "location_type": "bbox",
      "bbox": [-72.0, 45.0, -71.0, 46.0],
      "variables": ["tasmin", "tasmax", "pr"],
      "start_date": "2050-06-01",
      "end_date": "2050-08-31",
      "dataset": "cmip6_espo_g6_r2",
      "scenario": "ssp245",
      "model": "MPI-ESM1-2-LR"
    }
  }' | python3 -m json.tool
```

**Monthly aggregation — end-of-century full year**

```bash
curl -s -X POST http://<host>:5000/processes/climate-timeseries/execution \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {
      "location_type": "point",
      "point": [-71.5, 45.5],
      "variables": ["tasmin", "tasmax"],
      "start_date": "2080-01-01",
      "end_date": "2100-12-31",
      "dataset": "cmip6_espo_g6_r2",
      "scenario": "ssp585",
      "model": "CanESM5",
      "aggregation": "monthly"
    }
  }' | python3 -m json.tool
```

---

## Process: `climate-indicators`

Computes agronomic climate indicators from gridded weather data. Supports both historical reanalysis (ERA5-Land, RDRS) and CMIP6 projections (ESPO-G6-R2).

### Indicators

| `indicator` | Description | Variables fetched | Extra parameter |
| --- | --- | --- | --- |
| `gdd` | Growing Degree Days | `tasmin` + `tasmax` | `base_temp` |
| `frost_days` | Days where Tmin < 0 °C | `tasmin` | — |
| `heat_stress_days` | Days where Tmax > threshold | `tasmax` | `threshold` (default 30 °C) |
| `pr_total` | Total precipitation (mm) | `pr` | — |
| `pr_days` | Days with precipitation > threshold | `pr` | `threshold` (**pass explicitly**) |

### Parameters

| Parameter | Type | Required | Default | Constraints |
| --- | --- | --- | --- | --- |
| `location_type` | string | yes | — | see table above |
| `indicator` | string | yes | — | see indicators table |
| `start_date` | string | yes | — | `YYYY-MM-DD` |
| `end_date` | string | yes | — | `YYYY-MM-DD`; ≥ start_date |
| `dataset` | string | no | `era5_land` | `era5_land` `rdrs_v2_1` `cmip6_espo_g6_r2` |
| `scenario` | string | CMIP6 only | — | `ssp245` `ssp370` `ssp585` |
| `model` | string | CMIP6 only | — | any model from the table above |
| `base_temp` | number | no | `5.0` °C | 0–15; only used by `gdd` |
| `threshold` | number | no | `30.0` | 0–50; used by `heat_stress_days` and `pr_days` |

> **`base_temp` agronomic reference values:**
> `0.0` °C — cool-season crops (winter wheat, canola)
> `5.0` °C — most cereals (default)
> `10.0` °C — corn and warm-season crops

> **`pr_days` threshold:** the model default `30.0` is shared with `heat_stress_days`.
> For wet-day counts, always pass `"threshold": 1.0` explicitly — omitting it will
> count days with precipitation > 30 mm/day, which is almost always 0.

### Examples

**gdd — ERA5-Land historical, corn base temperature**

```bash
curl -s -X POST http://<host>:5000/processes/climate-indicators/execution \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {
      "location_type": "bbox",
      "bbox": [-72.0, 45.0, -71.0, 46.0],
      "indicator": "gdd",
      "base_temp": 10.0,
      "start_date": "2020-05-01",
      "end_date": "2020-09-30",
      "dataset": "era5_land"
    }
  }' | python3 -m json.tool
```

**frost_days — RDRS historical, spring frost risk**

```bash
curl -s -X POST http://<host>:5000/processes/climate-indicators/execution \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {
      "location_type": "point",
      "point": [-71.5, 45.5],
      "indicator": "frost_days",
      "start_date": "2015-04-01",
      "end_date": "2015-06-15",
      "dataset": "rdrs_v2_1"
    }
  }' | python3 -m json.tool
```

**heat_stress_days — CMIP6 projection, custom threshold**

```bash
curl -s -X POST http://<host>:5000/processes/climate-indicators/execution \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {
      "location_type": "bbox",
      "bbox": [-72.0, 45.0, -71.0, 46.0],
      "indicator": "heat_stress_days",
      "threshold": 28.0,
      "start_date": "2070-06-01",
      "end_date": "2070-08-31",
      "dataset": "cmip6_espo_g6_r2",
      "scenario": "ssp585",
      "model": "MPI-ESM1-2-LR"
    }
  }' | python3 -m json.tool
```

**pr_total — ERA5-Land, growing season**

```bash
curl -s -X POST http://<host>:5000/processes/climate-indicators/execution \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {
      "location_type": "bbox",
      "bbox": [-72.0, 45.0, -71.0, 46.0],
      "indicator": "pr_total",
      "start_date": "2020-05-01",
      "end_date": "2020-08-31",
      "dataset": "era5_land"
    }
  }' | python3 -m json.tool
```

**pr_days — ERA5-Land, wet-day count (threshold required)**

```bash
curl -s -X POST http://<host>:5000/processes/climate-indicators/execution \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {
      "location_type": "bbox",
      "bbox": [-72.0, 45.0, -71.0, 46.0],
      "indicator": "pr_days",
      "threshold": 1.0,
      "start_date": "2020-05-01",
      "end_date": "2020-08-31",
      "dataset": "era5_land"
    }
  }' | python3 -m json.tool
```

**gdd — CMIP6 projection, end-of-century comparison**

```bash
curl -s -X POST http://<host>:5000/processes/climate-indicators/execution \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {
      "location_type": "farm_id",
      "farm_id": "42",
      "indicator": "gdd",
      "base_temp": 5.0,
      "start_date": "2090-04-01",
      "end_date": "2090-10-31",
      "dataset": "cmip6_espo_g6_r2",
      "scenario": "ssp370",
      "model": "CanESM5"
    }
  }' | python3 -m json.tool
```

---

## Caveats

| Item | Detail |
| --- | --- |
| Rolling end date | ERA5-Land end date = today − 90 days. Requesting beyond this returns a 400 error. |
| RDRS rotated-pole grid | Spatial subsetting uses a 2D lat/lon mask. All location types are supported. |
| ESPO-G6-R2 rotated-pole grid | Same approach as RDRS — 2D lat/lon mask. All location types are supported. |
| `tas` unavailable in CMIP6 | ESPO-G6-R2 does not provide mean temperature. Use `(tasmin + tasmax) / 2`. |
| EC-Earth3-CC / NESM3 | No ssp370 run — use ssp245 or ssp585 for those two models. |
| noleap calendar | CMIP6 datasets use a 365-day calendar (no leap years). Date strings remain `YYYY-MM-DD`. |
| `era5_land_hourly` variables | Only `tas` and `pr` are available (no `tasmin` / `tasmax`). |
| First-request latency | Opening an OPeNDAP connection takes a few seconds. Repeated queries hit an in-memory cache (TTL: 1 hour). |
| `pr_days` default threshold | The shared default (30 mm) is almost never right for precipitation counts — always pass `"threshold": 1.0` explicitly. |
