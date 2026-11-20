# LiDAR Flow Paths and LS Factor (`lidar-flowpath`)

## Overview

`lidar-flowpath` maps where water flows and concentrates in a field. It takes
the MRNF LiDAR terrain model (DTM) over the field plus an upstream margin and
returns four rasters cropped to the field:

| Layer | Content | Unit |
| --- | --- | --- |
| `filled_dtm` | DTM with closed depressions filled | m |
| `sca` | Specific catchment area: upslope area draining through the pixel, per unit contour width | m (m²/m) |
| `slope` | Slope of the unfilled DTM | % (rise / run × 100) |
| `ls` | RUSLE LS factor (slope length and steepness) | dimensionless |

The process maps flow paths and the erosion LS factor. It does **not** compute
runoff volumes or depths, which would need rainfall and infiltration, nor soil
loss. Full RUSLE (A = R·K·LS·C·P) is planned for a later version.

**Data source:** [Produits dérivés de base du LiDAR — Données Québec](https://www.donneesquebec.ca/recherche/dataset/produits-derives-de-base-du-lidar)
(MRNF `MNT` product, 1 m), the same tiles as [`lidar-fetch`](LIDAR_QUERY_SPECS.md).

---

## Inputs

| Input | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `location_type` | string | yes | — | `farm_id`, `polygon` or `bbox` (`point` is rejected) |
| `farm_id` | string | with `farm_id` | — | Row of `FARM_TABLE_NAME` |
| `polygon` | GeoJSON | with `polygon` | — | Polygon or MultiPolygon in EPSG:4326; invalid geometries are repaired |
| `bbox` | array | with `bbox` | — | `[minx, miny, maxx, maxy]` in EPSG:4326 |
| `upstream_margin_m` | integer | no | 300 | Margin added on every side of the field's bounding box, 0 to 1000 |
| `zones` | GeoJSON | no | — | FeatureCollection of 1 to 50 Polygon or MultiPolygon features (management zones), each with an optional `id` property |

**Limits:** the field's bounding box, measured in EPSG:32198, may not
exceed **5 km²** (about 500 ha), and the computation grid (that box widened
by the margin, at 2 m) may not exceed **4.5 million cells**. A long, thin
field with a large margin can pass the first limit but not the second. Both
are checked before any download.

Validation errors are translated (French by default, English with `lang=en`
or `Accept-Language: en`) and start with « Paramètres d'entrée invalides » /
"Invalid inputs".

---

## Computation

### Terrain grid

1. The field is projected to **EPSG:32198** (NAD83 / Québec Lambert). Its
   bounding box is snapped outwards to the 2 m grid, then widened by
   `upstream_margin_m` and snapped again.
2. One `gdalwarp` call streams the 1 m MNT tiles over `/vsicurl/` and
   resamples them to **2 m** with `-r average`. Averaging aggregates 1 m to
   2 m and damps tillage micro-relief. No other smoothing is applied.
3. All four layers are computed on this margin grid, so flow entering the
   field from upslope is counted, and are then cropped to the field.

### Algorithms

| Step | Method | Reference |
| --- | --- | --- |
| Depression filling | Priority-Flood + ε (ε = 1e-4 m): every valid cell drains to the grid edge or to a nodata cell, and filled flats keep a strictly decreasing path | Barnes, Lehman & Mulla (2014), *Computers & Geosciences* 62 |
| Flow routing | Multiple flow direction, exponent 1.1, contour-length factors 0.5 (cardinal) and 0.354 (diagonal), on the filled DTM | Freeman (1991), *Computers & Geosciences* 17; Quinn et al. (1991), *Hydrological Processes* 5 |
| Slope | Horn 3×3 gradient on the **unfilled** DTM; missing neighbours take the centre value | Horn (1981), *Proceedings of the IEEE* 69 |
| LS factor | LS = (As / 22.13)^0.4 × (sin β / 0.0896)^1.3, with As the specific catchment area capped at 300 m (RUSLE slope-length validity) | Moore & Burch (1986), *SSSA Journal* 50 |

The implementation (`processes/hydro_backend/`) is written from these papers
using numpy only.

---

## Outputs

### COGs

Four float32 Cloud Optimized GeoTIFFs per field and margin, in EPSG:32198 at
2 m, DEFLATE, 512 px blocks, nearest-neighbour overviews:

```text
lidar_flowpath_<layer>_<identifier>_m<margin>_v<algorithm_version>.tif
```

- `<identifier>` is `farm_<id>`, or `geom_<16 hex>`, a hash of the exact field
  geometry.
- Pixels outside the field polygon, and nodata pixels, are **−9999**.

### Cache

The layers are reused when all four COGs of the same field, margin and
algorithm version exist. A cache hit downloads no terrain and runs no
computation; if the STAC publish markers are missing (STAC API down on the
first run), it only looks the tile index up again and republishes the
items. `zones` are not part of the key: re-running a field with other
zones only recomputes the summary. `ALGORITHM_VERSION` in
`processes/lidar_flowpath.py` is bumped whenever output values change, so
old layers are never served. As for `lidar-fetch`, nothing is deleted; a
field takes a few MB.

### STAC

One item per layer in the **`lidar_flowpath`** collection (created on first
run), with `proj:code` `EPSG:32198`, `agri_sdss:sheets` (the MRNF sheets read),
and the data asset plus `preview` (PNG) and `tilejson` renderings through
raster-api. Re-running updates existing items.

### Result

```json
{
  "stac_items": ["lidar_flowpath_filled_dtm_geom_1a2b3c4d5e6f7a8b_m300_v1", "..."],
  "assets": {
    "ls": {
      "href": "https://<host>/cog/lidar_flowpath_ls_geom_1a2b3c4d5e6f7a8b_m300_v1.tif",
      "type": "image/tiff; application=geotiff; profile=cloud-optimized",
      "title": "RUSLE LS factor",
      "bands": [{ "name": "ls", "nodata": -9999, "data_type": "float32", "statistics": { "mean": 0.82 } }],
      "preview": "https://<host>/raster-api/cog/preview.png?url=/data/...",
      "tilejson": "https://<host>/raster-api/cog/WebMercatorQuad/tilejson.json?url=/data/..."
    },
    "filled_dtm": { "...": "..." }, "sca": { "...": "..." }, "slope": { "...": "..." }
  },
  "bbox": [-72.96, 45.62, -72.95, 45.63],
  "summary": {
    "slope": { "mean_percent": 2.4 },
    "ls": { "mean": 0.82, "median": 0.41, "p90": 1.9, "max": 14.7 },
    "zones": [
      { "id": "A", "area_ha": 3.2, "slope": { "mean_percent": 1.8 },
        "ls": { "mean": 0.5, "median": 0.3, "p90": 1.1, "max": 6.2 } }
    ]
  },
  "parameters": {
    "upstream_margin_m": 300, "resolution_m": 2.0, "crs": "EPSG:32198",
    "resampling": "average", "sca_cap_m": 300.0, "mfd_exponent": 1.1,
    "fill_epsilon_m": 0.0001, "algorithm_version": 1
  },
  "source": {
    "dataset": "Produits dérivés de base du LiDAR (MRNF)",
    "url": "https://www.donneesquebec.ca/recherche/dataset/produits-derives-de-base-du-lidar",
    "sheets": ["31H03SE"]
  }
}
```

- `summary` statistics use only pixels inside the field polygon. `ls.max` is
  a single pixel; prefer `median` and `p90` to describe a field.
- `summary.zones` appears only when `zones` is sent: one entry per zone, in
  input order. `id` is the feature's `id` property, or its 1-based position.
  `area_ha` counts the zone's pixels inside the field. A zone that contains
  no pixel centre has `area_ha` 0 and null statistics. A zone that does not
  intersect the field is an `Invalid inputs` error.
- `parameters` and `source` are the assumptions to declare with the results.
  The LiDAR survey date is not available: neither the MRNF tile index nor the
  GeoTIFF metadata carries it. Look it up from `source.sheets` on the MRNF
  portal.

---

## Errors

| Situation | Answer |
| --- | --- |
| Field bounding box over 5 km² | Translated error stating the area and the limit; nothing is downloaded |
| Computation grid over 4.5 M cells | Translated error stating the cell count and the limit; nothing is downloaded |
| A zone outside the field | Translated `Invalid inputs` error naming the zone; nothing is downloaded |
| No MRNF DTM tile covers the area, or the field has only nodata | Translated « No LiDAR tiles found for the supplied geometry … » error; nothing is published |
| `gdalwarp` fails | Translated « Could not prepare the terrain model … » error |
| GDAL work exceeds 570 s | Translated time-limit error (shared with `lidar-fetch`) |
| Anything else | Generic translated error; the English cause is logged |

---

## Execution and run time

Run it asynchronously (`Prefer: respond-async`): process-api answers `201`
with a job URL, and `process-worker` runs the job (see
[process-api/CLAUDE.md](../CLAUDE.md#execution-model)).

The hydrology on the worst case (5 km² field with a 1000 m margin, 2 120 ×
2 120 cells) took **17.5 s** and peaked at **706 MB** in the process-api
image (2026-11-18). A typical 10–50 ha field with the default margin takes a
few seconds of computation; tile streaming adds tens of seconds depending on
the network.

---

## Reading the COGs elsewhere (Lambda, QGIS, scripts)

`assets.<layer>.href` is a public HTTPS URL (`/cog/<file>.tif`) served by the
home nginx. It needs no authentication and no STAC access, and it answers
byte-range requests, so GDAL and rasterio read only the blocks they need:

```python
import rasterio

with rasterio.open("/vsicurl/https://<host>/cog/lidar_flowpath_ls_geom_1a2b3c4d5e6f7a8b_m300_v1.tif") as src:
    ls = src.read(1, masked=True)
```

This works the same from AWS Lambda (GDAL `/vsicurl/`). `/cog/` is
rate-limited, so read windows rather than looping over many small requests.

---

## Limitations

- **Coverage edge.** Where the margin runs past MRNF coverage, nodata cells act
  as outlets, so flow from outside the coverage is not counted.
- **No smoothing.** Only the 1 m → 2 m average is applied. Results differ from
  tools that smooth the DTM before routing (for example plandeferme.ca).
- **2 m slopes are gentler** than MRNF's 1 m `Pentes` product on sharp breaks.
- **Retention.** Layers are kept indefinitely, like `lidar-fetch`.
- **No survey date** (see Result).
