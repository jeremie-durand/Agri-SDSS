# MSC GeoMet Observations — Query Specifications

Process: `POST /processes/msc-observations/execution`

Retrieves surface weather station observations from the Meteorological Service of Canada
(MSC) GeoMet OGC API (`https://api.weather.gc.ca`). No authentication required.
Returns a GeoJSON **FeatureCollection** with one Feature per station found within the
requested area.

---

## Collections

| `collection` | Period | Frequency | Notes |
| --- | --- | --- | --- |
| `climate-daily` *(default)* | 1840-01-01 → ~2 days ago | Daily | Structured daily summaries; recommended for most use cases |
| `swob-realtime` | Last 30 days | Sub-hourly | Near real-time; complex schema; many observations per station |

---

## Variables

### `climate-daily`

| `variable` | MSC field | Output unit |
| --- | --- | --- |
| `tasmin` | `MIN_TEMPERATURE` | °C |
| `tasmax` | `MAX_TEMPERATURE` | °C |
| `tas` | `MEAN_TEMPERATURE` | °C |
| `pr` | `TOTAL_PRECIPITATION` | mm |
| `prsn` | `TOTAL_SNOW` | mm |
| `snd` | `SNOW_ON_GROUND` | cm |

### `swob-realtime`

| `variable` | MSC field | Output unit |
| --- | --- | --- |
| `tas` | `air_temp` | °C (instantaneous at observation time) |
| `tasmin` | `min_air_temp_pst1hr` | °C (minimum over the past 1 hour) |
| `tasmax` | `max_air_temp_pst1hr` | °C (maximum over the past 1 hour) |
| `pr` | `rnfl_amt_pst1hr` | mm (rainfall accumulation over the past 1 hour) |
| `hurs` | `rel_hum` | % |
| `wss` | `avg_wnd_spd_10m_pst10mts` | km/h |

Missing values (`null` in the API) are returned as `null` in the timeseries.

---

## Location types

| `location_type` | Required field | Example value |
| --- | --- | --- |
| `"farm_id"` | `farm_id` | `"42"` |
| `"point"` | `point` | `[-71.5, 45.5]` |
| `"bbox"` | `bbox` | `[-74.0, 45.0, -73.0, 46.0]` |
| `"polygon"` | `polygon` | GeoJSON Polygon object |

All coordinates in EPSG:4326. The spatial filter is forwarded directly to the MSC
OGC API `bbox` parameter — only stations whose point geometry falls within the bbox
are returned.

---

## Parameters

| Parameter | Type | Required | Default | Constraints |
| --- | --- | --- | --- | --- |
| `location_type` | string | yes | — | see table above |
| `collection` | string | no | `climate-daily` | `climate-daily` or `swob-realtime` |
| `variables` | array | yes | — | ≥ 1 item; must be valid for selected collection |
| `start_date` | string | yes | — | `YYYY-MM-DD` |
| `end_date` | string | yes | — | `YYYY-MM-DD`; ≥ start_date |
| `limit` | integer | no | `500` | 1–5000; caps the number of **stations** returned |

---

## Examples

### `climate-daily` — bbox, temperature + precipitation

```bash
curl -s -X POST http://<host>:5000/processes/msc-observations/execution \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {
      "location_type": "bbox",
      "bbox": [-74.0, 45.0, -73.0, 46.0],
      "collection": "climate-daily",
      "variables": ["tasmin", "tasmax", "pr"],
      "start_date": "2024-01-01",
      "end_date": "2024-01-07"
    }
  }' | python3 -m json.tool
```

### `climate-daily` — point, full variable set

```bash
curl -s -X POST http://<host>:5000/processes/msc-observations/execution \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {
      "location_type": "point",
      "point": [-73.7494, 45.4706],
      "collection": "climate-daily",
      "variables": ["tasmin", "tasmax", "tas", "pr", "prsn", "snd"],
      "start_date": "2024-06-01",
      "end_date": "2024-08-31"
    }
  }' | python3 -m json.tool
```

### `swob-realtime` — bbox, last 7 days

```bash
curl -s -X POST http://<host>:5000/processes/msc-observations/execution \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {
      "location_type": "bbox",
      "bbox": [-74.0, 45.0, -73.0, 46.0],
      "collection": "swob-realtime",
      "variables": ["tas", "pr", "hurs"],
      "start_date": "2026-04-03",
      "end_date": "2026-04-10",
      "limit": 10
    }
  }' | python3 -m json.tool
```

---

## Response format

```json
{
  "id": "result",
  "value": {
    "type": "FeatureCollection",
    "provider": "msc-geomet",
    "collection": "climate-daily",
    "temporal_extent": ["2024-01-01", "2024-01-07"],
    "variables": ["tasmin", "tasmax"],
    "features": [
      {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [-73.7494, 45.4706]},
        "properties": {
          "provider": "msc-geomet",
          "station_name": "MONTREAL/PIERRE ELLIOTT TRUDEAU INTL A",
          "station_id": "7025251",
          "province": "QC",
          "variables": ["tasmin", "tasmax"],
          "data": {
            "time": ["2024-01-01", "2024-01-02", "2024-01-03"],
            "tasmin": [-12.3, -8.1, -5.4],
            "tasmax": [-4.5, -1.2, 2.0]
          },
          "units": {"tasmin": "degC", "tasmax": "degC"}
        }
      }
    ]
  }
}
```

The `province` field is present for `climate-daily` features and absent for `swob-realtime`.

---

## Caveats

| Item | Detail |
| --- | --- |
| `climate-daily` lag | Data typically available up to 1–2 days before today. |
| Station closures | Many `climate-daily` stations closed decades ago. If a region returns no data for a recent period, try an earlier date range or switch to `swob-realtime`. For gap-free timeseries at any location use `weather-timeseries` (ERA5-Land). |
| `swob-realtime` volume | Sub-hourly data: a 7-day bbox query may return thousands of observations per station. Use `limit` to cap the number of stations returned. |
| Null values | Some stations do not measure all variables. Missing values are `null` in the timeseries. |
| Coverage | MSC data covers Canada only (approx. 42°N–84°N, 52°W–142°W). Queries outside this area return no stations. |
| Caching | Identical queries are served from an in-memory cache (TTL: 15 minutes). |
