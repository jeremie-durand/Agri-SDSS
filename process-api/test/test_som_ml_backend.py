"""Unit tests for SOM ML backend."""

import numpy as np
import pandas as pd
import pytest
from processes.som_backend.som_ml_backend import (
    SOMMLBackend,
    parse_soil_list,
)


@pytest.mark.unit
class TestParseSoilList:
    def test_single_type(self):
        assert parse_soil_list("[TILL Bon]") == ["TILL Bon"]

    def test_multiple_types(self):
        result = parse_soil_list("[SABLE Mauvais, LIMON Mauvais]")
        assert result == ["SABLE Mauvais", "LIMON Mauvais"]

    def test_empty_string(self):
        assert parse_soil_list("[]") == []

    def test_non_string_input(self):
        result = parse_soil_list(None)
        assert isinstance(result, list)


@pytest.mark.unit
class TestSOMMLBackendRun:
    def _make_df(self, n_fields: int = 20, n_images_per_field: int = 5) -> pd.DataFrame:
        """Build a minimal synthetic feature DataFrame.

        Uses 5 images per field so that inner-train steps accumulate >= 30 rows by step 2,
        satisfying the MIN_INNER_TRAIN_ROWS threshold in the Jadid algorithm.
        """
        rng = np.random.default_rng(42)
        rows = []
        for field_id in range(n_fields):
            for i in range(n_images_per_field):
                row: dict = {
                    "FIELD_ID": float(field_id),
                    "Image_ID": f"2019_0{500 + i}",
                    "mean_SOM": float(rng.uniform(2.0, 12.0)),
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

    def test_run_returns_predictions_and_metrics(self):
        df = self._make_df()
        result = SOMMLBackend().run(df, scenarios=["S1_spec_soil"])
        assert "predictions" in result
        assert "metrics" in result
        assert len(result["predictions"]) > 0
        assert len(result["metrics"]) == 1

    def test_prediction_row_has_required_keys(self):
        df = self._make_df()
        result = SOMMLBackend().run(df, scenarios=["S1_spec_soil"])
        pred = result["predictions"][0]
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
            assert key in pred, f"Missing key: {key}"

    def test_metrics_row_has_required_keys(self):
        df = self._make_df()
        result = SOMMLBackend().run(df, scenarios=["S1_spec_soil"])
        metric = result["metrics"][0]
        for key in (
            "scenario",
            "algo",
            "n_images_used",
            "RMSE_log",
            "MAE_log",
            "R2_log",
            "RMSE_lin",
            "MAE_lin",
            "R2_lin",
        ):
            assert key in metric, f"Missing key: {key}"

    def test_n_images_used_is_positive_integer(self):
        df = self._make_df()
        result = SOMMLBackend().run(df, scenarios=["S1_spec_soil"])
        n = result["metrics"][0]["n_images_used"]
        assert isinstance(n, int)
        assert n >= 1

    def test_missing_required_columns_raises(self):
        df = pd.DataFrame({"FIELD_ID": [1], "Image_ID": ["2019_0501"]})
        with pytest.raises(ValueError, match="Missing required columns"):
            SOMMLBackend().run(df)

    def test_unknown_scenario_skipped(self):
        df = self._make_df()
        result = SOMMLBackend().run(df, scenarios=["S1_spec_soil", "invalid_scenario"])
        scenarios_returned = [m["scenario"] for m in result["metrics"]]
        assert "invalid_scenario" not in scenarios_returned
