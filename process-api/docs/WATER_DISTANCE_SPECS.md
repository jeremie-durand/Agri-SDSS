# Water Distance — Query Specifications

Process: `POST /processes/water-distance/execution`

Returns the geodesic distance in metres from an agricultural parcel to the nearest
hydrographic feature (stream, river or water body) of the Quebec GRHQ network. The
SOM form uses it to fill the distance-to-water field.

**Implementation:** [water_distance.py](../processes/water_distance.py),
backend [spatial_backend/water.py](../processes/spatial_backend/water.py)

---

## Prerequisites

| Store | Content | Requirement |
| --- | --- | --- |
| PostGIS | `WATER_TABLE_NAME` (default `public.grhq_water_union`) | GRHQ lines and polygons in a `geometry` column, EPSG:4326, with a GiST index |
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
| `max_distance_m` | number | no | `100000` | `> 0` and `≤ 100000` |

### How the distance is measured

- The distance is measured from **a point inside the parcel**
  (`ST_PointOnSurface`), not from its boundary: a stream crossing the parcel does
  not give 0. Unlike a centroid, this point stays inside an L-shaped or other
  concave parcel. A `point` input is used as is.
- An invalid polygon (for example a self-intersecting bow-tie) is repaired with
  shapely `make_valid`, keeping only its polygonal parts. An empty or unparsable
  geometry fails with a validation error.
- A KNN scan on the GiST index (`<->`) picks the 5 nearest candidates by planar
  distance in degrees; the exact geography distance is then computed on those
  rows only, and the smallest is returned. The interior point is written inline
  in the `ORDER BY` rather than in a CTE so the planner keeps the index scan.
- When the nearest feature is farther than `max_distance_m`, `distance_m` is
  `null`.

---

## Example

```bash
curl -s -X POST https://<host>/process-api/processes/water-distance/execution \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {
      "location_type": "polygon",
      "polygon": {
        "type": "Polygon",
        "coordinates": [[[-72.0, 45.0], [-71.99, 45.0], [-71.99, 45.01],
                         [-72.0, 45.01], [-72.0, 45.0]]]
      }
    }
  }' | python3 -m json.tool
```

---

## Response

`application/json`:

```json
{
  "id": "result",
  "value": {"distance_m": 350.25}
}
```

`distance_m` is a number of metres, or `null` when no feature lies within
`max_distance_m`.

---

## Errors

| Case | Message (French by default) |
| --- | --- |
| Invalid inputs (`bbox`, missing location value, cutoff out of range) | `Invalid inputs: <field>: <reason>` translated |
| Empty or unparsable geometry | Translated geometry error |
| Database or other backend failure | `An unexpected error occurred while running this process.` translated; details are logged in English only |

---

## Caveats

| Item | Detail |
| --- | --- |
| Synchronous only | The process runs sync-execute. |
| KNN approximation | Candidates are ranked by planar distance in degrees, then measured geodesically. With 5 candidates the true nearest feature is almost always among them, but at high latitudes the planar ranking can differ from the geodesic one. |
| Coverage | GRHQ covers Quebec only; a parcel outside it usually returns `null` at the default cutoff. |

---

## References

- [OpenSpec requirements](../../openspec/specs/water-distance/spec.md)
- [Data catalog](../../docs/data/CATALOG.md)
