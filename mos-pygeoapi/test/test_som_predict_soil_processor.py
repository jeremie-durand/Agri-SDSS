"""Mocked integration tests for SOMPredictSoilProcessor."""

from unittest.mock import patch

import pandas as pd
import pytest
from processes.som_predict_soil import SOMPredictSoilProcessor
from pygeoapi.process.base import ProcessorExecuteError


def _make_processor() -> SOMPredictSoilProcessor:
    return SOMPredictSoilProcessor({"name": "som-predict-soil"})


def _minimal_preds_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "row_id": 0,
                "FIELD_ID": 416,
                "Image_ID": "2019_0505",
                "y_true_lin": 3.8,
                "y_pred_lin": 5.1,
                "y_true_log": 0.58,
                "y_pred_log": 0.70,
                "algo": "RandomForest",
                "scenario": "S1_spec_soil",
            }
        ]
    )


def _minimal_feature_df() -> pd.DataFrame:
    import numpy as np

    rng = np.random.default_rng(0)
    rows = []
    for fid in [416, 417]:
        for img in ["2019_0505", "2019_0612"]:
            row: dict = {
                "FIELD_ID": float(fid),
                "Image_ID": img,
                "mean_SOM": float(rng.uniform(3.0, 10.0)),
                "soilTypes": "[TILL Bon]",
            }
            for col in [
                "BI_mean",
                "CI_mean",
                "NDMI_mean",
                "OMI_mean",
                "RI_mean",
                "SI_mean",
                "EVI_mean",
                "SAVI_mean",
                "NDVI_mean",
                "BSI_mean",
                "CAI_mean",
                "BI_stdDev",
                "CI_stdDev",
                "NDMI_stdDev",
                "OMI_stdDev",
                "RI_stdDev",
                "SI_stdDev",
                "EVI_stdDev",
                "SAVI_stdDev",
                "NDVI_stdDev",
                "BSI_stdDev",
                "CAI_stdDev",
            ]:
                row[col] = float(rng.uniform(-1.0, 1.0))
            rows.append(row)
    return pd.DataFrame(rows)


@pytest.mark.mocked
class TestSOMPredictSoilProcessorValidation:
    def test_empty_field_ids_raises(self):
        proc = _make_processor()
        with pytest.raises(ProcessorExecuteError, match="field_ids"):
            proc.execute({"field_ids": []})

    def test_missing_field_ids_raises(self):
        proc = _make_processor()
        with pytest.raises(ProcessorExecuteError, match="field_ids"):
            proc.execute({})

    def test_invalid_scenario_raises(self):
        proc = _make_processor()
        with patch.object(
            proc, "_load_features_from_duckdb", return_value=_minimal_feature_df()
        ):
            with pytest.raises(ProcessorExecuteError, match="Unknown scenarios"):
                proc.execute({"field_ids": [416], "scenarios": ["invalid"]})

    def test_non_integer_field_ids_raises(self):
        proc = _make_processor()
        with pytest.raises(ProcessorExecuteError, match="integers"):
            proc.execute({"field_ids": ["not_an_int"]})


@pytest.mark.mocked
class TestSOMPredictSoilProcessorDuckDB:
    def test_missing_parquet_files_raises(self, tmp_path):
        proc = _make_processor()
        with patch.dict("os.environ", {"DUCKDB_DATA_DIR": str(tmp_path)}):
            with pytest.raises(ProcessorExecuteError, match="No GEE feature Parquet"):
                proc.execute({"field_ids": [416]})

    def test_no_matching_rows_raises(self, tmp_path):
        proc = _make_processor()
        # Create a dummy parquet with different FIELD_IDs using duckdb (no pyarrow needed)
        import duckdb

        con = duckdb.connect()
        con.execute(
            f"COPY (SELECT 999.0 AS FIELD_ID, '2019_0505' AS Image_ID) "
            f"TO '{tmp_path}/BareSoil_TOPCLI_2019_Part01.parquet' (FORMAT PARQUET)"
        )
        con.close()
        with patch.dict("os.environ", {"DUCKDB_DATA_DIR": str(tmp_path)}):
            with pytest.raises(ProcessorExecuteError, match="No feature data found"):
                proc.execute({"field_ids": [416]})


@pytest.mark.mocked
class TestSOMPredictSoilProcessorHappyPath:
    def test_returns_geojson_feature_collection(self):
        proc = _make_processor()
        preds_df = _minimal_preds_df()
        mock_ml_result = {
            "predictions": preds_df.to_dict(orient="records"),
            "metrics": [
                {
                    "scenario": "S1_spec_soil",
                    "algo": "RandomForest",
                    "RMSE_log": 0.1,
                    "MAE_log": 0.08,
                    "R2_log": 0.9,
                    "RMSE_lin": 0.5,
                    "MAE_lin": 0.4,
                    "R2_lin": 0.85,
                    "n_images_used": 5,
                }
            ],
        }
        mock_field_result = {
            "field_predictions": [{"FIELD_ID": 416, "n_images": 1}],
            "field_metrics": [
                {"Algo": "RandomForest", "Scenario": "S1_spec_soil", "n_fields": 1}
            ],
        }

        with patch.object(
            proc, "_load_features_from_duckdb", return_value=_minimal_feature_df()
        ), patch.object(
            proc._ml_backend, "run", return_value=mock_ml_result
        ), patch.object(
            proc._field_backend, "run", return_value=mock_field_result
        ), patch.object(
            proc, "_fetch_field_geometries", return_value={416: None}
        ):

            mime, result = proc.execute(
                {"field_ids": [416], "scenarios": ["S1_spec_soil"]}
            )

        assert mime == "application/geo+json"
        assert result["id"] == "result"
        fc = result["value"]
        assert fc["type"] == "FeatureCollection"
        assert "features" in fc
        assert "field_summary" in fc
        assert len(fc["features"]) == len(preds_df)

    def test_feature_properties_shape(self):
        proc = _make_processor()
        preds_df = _minimal_preds_df()
        mock_ml_result = {
            "predictions": preds_df.to_dict(orient="records"),
            "metrics": [],
        }
        mock_field_result = {"field_predictions": [], "field_metrics": []}

        with patch.object(
            proc, "_load_features_from_duckdb", return_value=_minimal_feature_df()
        ), patch.object(
            proc._ml_backend, "run", return_value=mock_ml_result
        ), patch.object(
            proc._field_backend, "run", return_value=mock_field_result
        ), patch.object(
            proc, "_fetch_field_geometries", return_value={416: None}
        ):

            _, result = proc.execute(
                {"field_ids": [416], "scenarios": ["S1_spec_soil"]}
            )

        feature = result["value"]["features"][0]
        props = feature["properties"]
        for key in (
            "FIELD_ID",
            "Image_ID",
            "y_true_lin",
            "y_pred_lin",
            "y_true_log",
            "y_pred_log",
            "algo",
            "scenario",
        ):
            assert key in props, f"Missing property: {key}"
