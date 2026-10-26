# Pedological Coverage — Query Specifications

Process: `POST /processes/pedo-coverage/execution`

Returns the pedological classes covering an agricultural parcel and the share of
its area each covers, from the IRDA 2026 soil map, falling back to the IRDA 2022
map where the 2026 release does not cover the parcel well enough. The SOM form
uses it to fill the soil-class field.

**Implementation:** [pedo_coverage.py](../processes/pedo_coverage.py),
backend [spatial_backend/pedo.py](../processes/spatial_backend/pedo.py)

---

## Prerequisites

| Store | Content | Requirement |
| --- | --- | --- |
| PostGIS | `PEDO_TABLE_NAME` (default `public.couverture_pedologique_2026_01_couverture_p_cbc3c8`) | IRDA 2026 polygon map: `symbole` and a `geometry` column in EPSG:4326, with a GiST index |
| PostGIS | `PEDO_2022_TABLE_NAME` (default `public.couverture_pedo_2022`) | IRDA 2022 map: `symbol`, `description` and a `geometry` column in EPSG:4326, with a GiST index |
| PostGIS | `FARM_TABLE_NAME` | Farm geometries, only for `location_type: "farm_id"` |

Table names come from the environment (`SpatialTablesConfig`) and must match
`^[a-zA-Z0-9_.]+$`; any other value is refused before the query runs.

---

## The two IRDA releases

| Release | `source` | Class column | `description` |
| --- | --- | --- | --- |
| IRDA 2026 | `irda_2026` | `symbole` | always `null` |
| IRDA 2022 | `irda_2022` | `symbol` | the map unit's soil description |

Both releases use the same class scheme (`ARGILE Bon`, `TILL Imparfait`,
`Étendue d'eau`, `Île`, `AFFLEUREMENT`…) and cover essentially the same area.

2026 classes have no description because the IRDA 2026 component table
`couverture_pps` lacks the dominant component (`numero_composante = 1`) of every
polygon. A description joined from it would be the second component's, so the
process returns `null` rather than a wrong soil series. Descriptions will be
added once `couverture_pps` is re-imported.

---

## Parameters

| Parameter | Type | Required | Default | Constraints |
| --- | --- | --- | --- | --- |
| `location_type` | string | yes | — | `farm_id`, `point` or `polygon`; `bbox` is rejected |
| `farm_id` | string | when `farm_id` | — | Existing farm identifier |
| `point` | `[lon, lat]` | when `point` | — | EPSG:4326 |
| `polygon` | GeoJSON object | when `polygon` | — | `Polygon` or `MultiPolygon`, EPSG:4326 |
| `min_described_pct` | number | no | `50` | `0` to `100` |

### How classes are computed

- Map polygons intersecting the parcel are found through the GiST index
  (`ST_Intersects`). For each class, `share_pct` is the geodesic area of its
  intersection with the parcel divided by the parcel area, × 100; polygons of
  the same class are summed, so each class appears once.
- `described_pct` is the sum of all `share_pct`. It is below 100 where the map
  has gaps or ends inside the parcel; shares are never rescaled to 100.
- A `point` is buffered by 5 m (geodesic) so area shares are defined. An invalid
  polygon is repaired with shapely `make_valid`, keeping only its polygonal
  parts.
- Every class the map assigns is kept, including non-soil classes such as
  `Étendue d'eau`, `Île` and `AFFLEUREMENT`.

### Fallback rule

```text
2026 query
  ├─ described_pct ≥ min_described_pct ─► irda_2026
  └─ below ─► 2022 query
               ├─ any class ─► irda_2022
               └─ none ─► the partial 2026 result (irda_2026), or empty
```

A result never mixes the two releases. Both queries run on one connection, so a
fallback costs one extra indexed query. With `min_described_pct: 0`, 2022 is
never queried; with `100`, any parcel the 2026 map does not fully cover is
described from 2022 when 2022 has classes there.

---

## Example

```bash
curl -s -X POST https://<host>/process-api/processes/pedo-coverage/execution \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {
      "location_type": "point",
      "point": [-72.0, 45.4],
      "min_described_pct": 50
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
    "source": "irda_2026",
    "symbole": "ARGILE Bon",
    "description": null,
    "count": 2,
    "described_pct": 100.0,
    "classes": [
      {"symbole": "ARGILE Bon", "description": null, "share_pct": 62.0},
      {"symbole": "TILL Bon", "description": null, "share_pct": 38.0}
    ]
  }
}
```

- `classes` is ordered by decreasing `share_pct`; `symbole` and `description`
  repeat the first class.
- `count` is the number of distinct classes, not the number of map polygons.
- Shares are rounded to 0.1 %.
- Outside both releases, `source`, `symbole` and `description` are `null`,
  `count` and `described_pct` are 0 and `classes` is empty.

---

## Errors

| Case | Message (French by default) |
| --- | --- |
| Invalid inputs (`bbox`, missing location value, threshold out of range) | `Invalid inputs: <field>: <reason>` translated |
| Empty or unparsable geometry | Translated geometry error |
| Database or other backend failure | `An unexpected error occurred while running this process.` translated; details are logged in English only |

---

## Caveats

| Item | Detail |
| --- | --- |
| Synchronous only | The process runs sync-execute. |
| No 2026 descriptions | See [The two IRDA releases](#the-two-irda-releases). |
| Coverage | IRDA maps cover southern Quebec's agricultural land; elsewhere the result is empty. |

---

## References

- [OpenSpec requirements](../../openspec/specs/pedo-coverage/spec.md)
- [IRDA pedological map](../../docs/data/sources/CARTE_PEDOLOGIQUE_QUEBEC.md)
- [Data catalog](../../docs/data/CATALOG.md)
