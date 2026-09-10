"""Unit tests for SOM field-level aggregation backend."""

import pandas as pd
import pytest
from processes.som_backend.som_field_backend import (
    SOMFieldBackend,
    field_level_from_preds,
    metrics_per_group,
)


def _make_preds_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "FIELD_ID": 10,
                "Image_ID": "2019_0505",
                "y_true_log": 0.58,
                "y_pred_log": 0.70,
                "y_true_lin": 3.8,
                "y_pred_lin": 5.1,
                "algo": "RandomForest",
                "scenario": "S1_spec_soil",
            },
            {
                "FIELD_ID": 10,
                "Image_ID": "2019_0612",
                "y_true_log": 0.55,
                "y_pred_log": 0.65,
                "y_true_lin": 3.5,
                "y_pred_lin": 4.5,
                "algo": "RandomForest",
                "scenario": "S1_spec_soil",
            },
            {
                "FIELD_ID": 20,
                "Image_ID": "2019_0505",
                "y_true_log": 0.48,
                "y_pred_log": 0.60,
                "y_true_lin": 3.0,
                "y_pred_lin": 4.0,
                "algo": "RandomForest",
                "scenario": "S1_spec_soil",
            },
        ]
    )


@pytest.mark.unit
class TestFieldLevelFromPreds:
    def test_aggregates_by_field(self):
        df = _make_preds_df()
        fld = field_level_from_preds(df)
        assert set(fld["FIELD_ID"].tolist()) == {10, 20}

    def test_field_10_has_mean_of_two_images(self):
        df = _make_preds_df()
        fld = field_level_from_preds(df)
        row = fld[fld["FIELD_ID"] == 10].iloc[0]
        assert row["n_images"] == 2
        assert abs(row["y_true_log_field"] - (0.58 + 0.55) / 2) < 1e-6

    def test_missing_columns_raises(self):
        with pytest.raises(KeyError, match="Missing columns"):
            field_level_from_preds(pd.DataFrame({"FIELD_ID": [1]}))


@pytest.mark.unit
class TestMetricsPerGroup:
    def test_returns_one_row_per_algo_scenario(self):
        fld = field_level_from_preds(_make_preds_df())
        summary = metrics_per_group(fld)
        assert len(summary) == 1
        assert summary.iloc[0]["Scenario"] == "S1_spec_soil"

    def test_metric_columns_present(self):
        fld = field_level_from_preds(_make_preds_df())
        summary = metrics_per_group(fld)
        for col in (
            "RMSE_log",
            "MAE_log",
            "R2_log",
            "RMSE_lin",
            "MAE_lin",
            "R2_lin",
            "n_fields",
        ):
            assert col in summary.columns


@pytest.mark.unit
class TestSOMFieldBackendRun:
    def test_run_returns_expected_structure(self):
        result = SOMFieldBackend().run(_make_preds_df())
        assert "field_predictions" in result
        assert "field_metrics" in result

    def test_field_predictions_have_required_keys(self):
        result = SOMFieldBackend().run(_make_preds_df())
        pred = result["field_predictions"][0]
        for key in (
            "FIELD_ID",
            "algo",
            "scenario",
            "y_true_log_field",
            "y_pred_log_field",
            "n_images",
        ):
            assert key in pred

    def test_all_values_are_json_serialisable(self):
        import json

        result = SOMFieldBackend().run(_make_preds_df())
        json.dumps(result)  # raises if not serialisable
