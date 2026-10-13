# SOM Soil Prediction — Query Specifications

Process: `POST /processes/som-predict-soil/execution`

Predicts Soil Organic Matter (SOM) for selected agricultural field IDs using a
RandomForest model trained on GEE-derived bare-soil spectral indices, topographic
features, and bioclimatic variables (2019–2023). Returns a GeoJSON FeatureCollection
with one Feature per image-level prediction and per-field aggregated metrics.

**Implementation:** [som_predict_soil.py](../processes/som_predict_soil.py)

---

## Prerequisites

The process reads from both platform stores — run the gis-pipeline on the prepared
SOM data first:

| Store | Content | Requirement |
| --- | --- | --- |
| PostGIS | `som_field_boundaries` table | Polygon geometries keyed by `gid`; `gee_field_id` holds the GEE `FIELD_ID` of each field with GEE data (stamped by gis-pipeline) |
| DuckDB | `BareSoil_TOPCLI_*.parquet` files in `DUCKDB_DATA_DIR` | GEE feature rows (spectral, topographic, climate) queryable by `FIELD_ID` |

`gid` and the GEE `FIELD_ID` are different identifiers: GEE numbered the fields in
another order. The process translates the requested `gid` values through
`gee_field_id` before reading the Parquet files.

If none of the requested `gid` values has a `gee_field_id`, or if the Parquet files
are missing or contain no rows for the resolved IDs, the process returns a
descriptive `ProcessorExecuteError`. Requested `gid` values without GEE data are
skipped with a warning when at least one other value has data.

---

## Scenarios

Each scenario adds more feature groups to the model:

| `scenarios` value | Features used |
| --- | --- |
| `S1_spec_soil` | Bare-soil spectral indices + soil types |
| `S2_spec_soil_topo` | S1 + topography |
| `S3_spec_soil_topo_clim` | S2 + bioclimatic variables |

By default all three scenarios run; pass a subset to run fewer.

---

## Parameters

| Parameter | Type | Required | Default | Constraints |
| --- | --- | --- | --- | --- |
| `field_ids` | array of integers | yes | — | ≥ 1 ID; `gid` values of `som_field_boundaries` (not GEE `FIELD_ID`) |
| `scenarios` | array of strings | no | all three | values from the scenarios table |

### How predictions are produced

The model for a scenario is trained once on **all** labelled fields in the GEE
feature data and cached, keyed on the scenario and a fingerprint of the source
Parquet files. Requested `field_ids` select which fields to *report*, not which
to hold out — so a requested field is normally part of the training set.

To keep the served numbers out-of-sample anyway, the RandomForest is fitted with
`oob_score=True` and each field is answered with its **out-of-bag** prediction:
the estimate from only those trees that did not see that row during fitting.
The Duan smearing factor applied on the log → linear retransformation is derived from the same out-of-bag residuals.

Rows the model has genuinely never seen fall back to an ordinary prediction.

---

## Example

```bash
curl -s -X POST https://<host>/process-api/processes/som-predict-soil/execution \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {
      "field_ids": [195, 196, 48, 49],
      "scenarios": ["S3_spec_soil_topo_clim"]
    }
  }' | python3 -m json.tool
```

---

## Response

`application/geo+json` — a FeatureCollection with a top-level `field_summary` key:

```json
{
  "id": "result",
  "value": {
    "type": "FeatureCollection",
    "field_summary": [
      {
        "FIELD_ID": 416,
        "Scenario": "S3_spec_soil_topo_clim",
        "RMSE_log": 0.08, "MAE_log": 0.06, "R2_log": 0.71,
        "RMSE_lin": 0.42, "MAE_lin": 0.31, "R2_lin": 0.68,
        "r2_source": "test",
        "n_images": 12, "n_images_used": 12
      }
    ],
    "features": [
      {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": ["..."]},
        "properties": {
          "row_id": 0,
          "gid": 195,
          "FIELD_ID": 416,
          "Image_ID": "20210514T154911",
          "y_true_lin": 3.1, "y_pred_lin": 2.9,
          "y_true_log": 0.49, "y_pred_log": 0.46,
          "algo": "RandomForest",
          "scenario": "S3_spec_soil_topo_clim"
        }
      }
    ]
  }
}
```

- One Feature per image-level prediction (a field usually has several images).
- Each Feature carries both identifiers: `gid` (the polygon in
  `som_field_boundaries`, as requested) and `FIELD_ID` (the GEE field).
- Geometries come from the `som_field_boundaries` row of that `gid`.
- When a field has too few test images for a defined R², `R2_lin` falls back to the
  scenario validation R² and `r2_source` is set to `"val"` instead of `"test"`.

---

## Caveats

| Item | Detail |
| --- | --- |
| Synchronous only | The process runs sync-execute. The first request for a scenario trains and caches the model; later requests reuse it unless the source data changes. |
| Out-of-bag estimates | Reported values are out-of-bag, not held-out-set, predictions. They are out-of-sample per row but come from a model fitted on the full labelled dataset. |
| NaN handling | All NaN/Inf values in the response are converted to JSON `null`. |
| No plots | Matplotlib runs with the `Agg` backend — the process never writes plot files. |
| Data coverage | Only `gid` values with a `gee_field_id` can be predicted. Others are skipped with a warning; if none has one, the process raises an error listing them. |

---

## References

- [OpenSpec requirements](../../openspec/specs/som-predict-soil/spec.md)
- [Data catalog](../../docs/data/CATALOG.md)
