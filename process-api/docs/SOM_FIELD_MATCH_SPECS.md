# SOM Field Match — Query Specifications

Process: `POST /processes/som-field-match/execution`

Returns the SOM field boundaries within a tolerance of a parcel, and whether GEE
training data exists for each. The SOM form calls it to find the fields of a
parcel and enable prediction; the returned `gid` values are the `field_ids` that
[som-predict-soil](SOM_PREDICT_SOIL_SPECS.md) expects.

**Implementation:** [som_field_match.py](../processes/som_field_match.py),
backend [spatial_backend/som_fields.py](../processes/spatial_backend/som_fields.py)

---

## Prerequisites

| Store | Content | Requirement |
| --- | --- | --- |
| PostGIS | `SOM_TABLE_NAME` (default `public.som_field_boundaries`) | `gid`, `has_gee_data` and a `geometry` column in EPSG:4326, with a GiST index; ingested by gis-pipeline |
| PostGIS | `FARM_TABLE_NAME` | Farm geometries, only for `location_type: "farm_id"` |

Table names come from the environment (`SpatialTablesConfig`) and must match
`^[a-zA-Z0-9_.]+$`; any other value is refused before the query runs.

---

## Parameters

| Parameter | Type | Required | Default | Constraints |
| --- | --- | --- | --- | --- |
| `location_type` | string | yes | — | `farm_id`, `point` or `polygon`; `bbox` is rejected |
| `farm_id` | string | when `farm_id` | — | Existing farm identifier |
| `point` | `[lon, lat]` | when `point` | — | EPSG:4326 |
| `polygon` | GeoJSON object | when `polygon` | — | `Polygon` or `MultiPolygon`, EPSG:4326 |
| `tolerance_m` | number | no | `20` | `0` to `500` |

### How fields are matched

- Every field whose geodesic distance to the location is at most `tolerance_m`
  is returned (`ST_DWithin` on geography). The tolerance absorbs the small
  offsets between parcel boundaries and SOM field boundaries drawn from
  different sources; an intersecting field has a distance of 0.
- Fields with GEE data come first, then by increasing distance.
- An invalid polygon (for example a self-intersecting bow-tie) is repaired with
  shapely `make_valid`, keeping only its polygonal parts. A `point` input is used
  as is.

---

## Example

```bash
curl -s -X POST https://<host>/process-api/processes/som-field-match/execution \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {
      "location_type": "point",
      "point": [-72.0, 45.4],
      "tolerance_m": 20
    }
  }' | python3 -m json.tool
```

---

## Response

`application/json`:

```json
{
  "id": "result",
  "value": {
    "matches": [
      {"gid": 12, "has_gee_data": true, "dist_m": 8.0},
      {"gid": 7, "has_gee_data": false, "dist_m": 0.0}
    ]
  }
}
```

- `gid` is the `som_field_boundaries` identifier, not the GEE `FIELD_ID`.
- `dist_m` is the geodesic distance in metres, rounded to 0.1 m.
- `matches` is empty when no field lies within `tolerance_m`.

---

## Errors

| Case | Message (French by default) |
| --- | --- |
| Invalid inputs (`bbox`, missing location value, tolerance out of range) | `Invalid inputs: <field>: <reason>` translated |
| Empty or unparsable geometry | Translated geometry error |
| Database or other backend failure | `An unexpected error occurred while running this process.` translated; details are logged in English only |

---

## Caveats

| Item | Detail |
| --- | --- |
| Synchronous only | The process runs sync-execute. |
| Coverage | Only parcels near a field of the SOM dataset match; elsewhere `matches` is empty. |

---

## References

- [OpenSpec requirements](../../openspec/specs/som-field-matching/spec.md)
- [SOM soil prediction](SOM_PREDICT_SOIL_SPECS.md)
- [Data catalog](../../docs/data/CATALOG.md)
