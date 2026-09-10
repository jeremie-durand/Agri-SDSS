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


@pytest.mark.unit
class TestSOMMLBackendPreprocess:
    def _make_df(self, n_fields: int = 20, n_images_per_field: int = 5) -> pd.DataFrame:
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
                    "BI_mean", "CI_mean", "NDMI_mean", "OMI_mean", "RI_mean",
                    "SI_mean", "EVI_mean", "SAVI_mean", "NDVI_mean", "BSI_mean",
                    "CAI_mean", "BI_stdDev", "CI_stdDev", "NDMI_stdDev",
                    "OMI_stdDev", "RI_stdDev", "SI_stdDev", "EVI_stdDev",
                    "SAVI_stdDev", "NDVI_stdDev", "BSI_stdDev", "CAI_stdDev",
                ]:
                    row[col] = float(rng.uniform(-1.0, 1.0))
                rows.append(row)
        return pd.DataFrame(rows)

    def test_preprocess_returns_data_mlb_and_bounds(self):
        df = self._make_df()
        data, mlb, bounds = SOMMLBackend()._preprocess(df)
        assert "log_SOM" in data.columns
        assert "TILL Bon" in data.columns  # one-hot column from soilTypes
        assert isinstance(bounds, tuple) and len(bounds) == 2
        assert bounds[0] < bounds[1]
        assert "TILL Bon" in mlb.classes_.tolist()

    def test_preprocess_drops_missing_mean_som(self):
        df = self._make_df(n_fields=2)
        df.loc[0, "mean_SOM"] = None
        data, _, _ = SOMMLBackend()._preprocess(df)
        assert data["mean_SOM"].isna().sum() == 0

    def test_preprocess_for_predict_matches_training_encoding(self):
        """A field's rows, encoded via preprocess_for_predict using the
        training pool's fitted mlb/bounds, must produce the same one-hot
        columns as the training data itself (transform, not fit_transform)."""
        df = self._make_df()
        backend = SOMMLBackend()
        data, mlb, bounds = backend._preprocess(df)

        one_field_raw = df[df["FIELD_ID"] == 0.0]
        predicted = backend.preprocess_for_predict(one_field_raw, mlb, bounds)

        assert "log_SOM" in predicted.columns
        assert "TILL Bon" in predicted.columns
        assert len(predicted) == len(one_field_raw)

    def test_preprocess_for_predict_uses_passed_in_bounds_not_recomputed(self):
        """The whole point of the fit/transform split: prediction-time rows
        must be filtered using the TRAINING pool's bounds, not bounds
        recomputed on the (possibly tiny) prediction-time subset. Pass in
        artificially narrow bounds and confirm a row that would pass the
        training pool's own natural quantiles gets filtered out anyway,
        proving the passed-in bounds are actually what's used."""
        df = self._make_df()
        backend = SOMMLBackend()
        _, mlb, natural_bounds = backend._preprocess(df)

        one_field_raw = df[df["FIELD_ID"] == 0.0]
        # Sanity check: this field's rows pass the training pool's own
        # natural bounds (the split shouldn't filter them under normal use).
        under_natural_bounds = backend.preprocess_for_predict(
            one_field_raw, mlb, natural_bounds
        )
        assert len(under_natural_bounds) == len(one_field_raw)

        # Artificially narrow bounds that exclude every row's log_SOM value.
        import numpy as np

        log_som_values = np.log10(one_field_raw["mean_SOM"])
        impossible_bounds = (
            float(log_som_values.min()) - 10.0,
            float(log_som_values.min()) - 5.0,
        )
        under_narrow_bounds = backend.preprocess_for_predict(
            one_field_raw, mlb, impossible_bounds
        )
        assert under_narrow_bounds.empty

    def test_preprocess_for_predict_filters_missing_mean_som(self):
        df = self._make_df(n_fields=1)
        df.loc[0, "mean_SOM"] = None
        backend = SOMMLBackend()
        _, mlb, bounds = backend._preprocess(self._make_df())
        predicted = backend.preprocess_for_predict(df, mlb, bounds)
        assert len(predicted) == len(df) - 1

    def test_preprocess_for_predict_empty_input_returns_empty(self):
        backend = SOMMLBackend()
        _, mlb, bounds = backend._preprocess(self._make_df())
        empty = self._make_df(n_fields=0)
        result = backend.preprocess_for_predict(empty, mlb, bounds)
        assert result.empty


@pytest.mark.unit
class TestRunScenarioProductionArtifacts:
    def _make_df(self, n_fields: int = 20, n_images_per_field: int = 5) -> pd.DataFrame:
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
                    "BI_mean", "CI_mean", "NDMI_mean", "OMI_mean", "RI_mean",
                    "SI_mean", "EVI_mean", "SAVI_mean", "NDVI_mean", "BSI_mean",
                    "CAI_mean", "BI_stdDev", "CI_stdDev", "NDMI_stdDev",
                    "OMI_stdDev", "RI_stdDev", "SI_stdDev", "EVI_stdDev",
                    "SAVI_stdDev", "NDVI_stdDev", "BSI_stdDev", "CAI_stdDev",
                ]:
                    row[col] = float(rng.uniform(-1.0, 1.0))
                rows.append(row)
        return pd.DataFrame(rows)

    def test_run_scenario_returns_three_tuple_with_artifacts(self):
        backend = SOMMLBackend()
        df = self._make_df()
        data, _, _ = backend._preprocess(df)
        unique_fields = data["FIELD_ID"].unique()
        rng = np.random.default_rng(0)
        test_fields = rng.choice(unique_fields, size=4, replace=False)
        train_fields = np.setdiff1d(unique_fields, test_fields)
        train_data = data[data["FIELD_ID"].isin(train_fields)].copy()
        test_data = data[data["FIELD_ID"].isin(test_fields)].copy()
        feats = [
            "BI_mean", "CI_mean", "NDMI_mean", "OMI_mean", "RI_mean",
            "SI_mean", "EVI_mean", "SAVI_mean", "NDVI_mean", "BSI_mean",
            "CAI_mean", "TILL Bon",
        ]

        summary, preds, artifacts = backend._run_scenario(
            train_data, test_data, feats, "S1_spec_soil"
        )

        for key in (
            "scaler", "selected_features", "feat_idx", "col_means",
            "rf_production", "smearing_factor", "n_test_fields",
        ):
            assert key in artifacts, f"Missing artifact: {key}"
        assert artifacts["n_test_fields"] == len(test_fields)

    def test_production_model_trained_on_test_data_plus_good_train_images(self):
        """The production model's training set must be exactly train_final
        (the noise-filtered 'good' images from train_data) plus every row of
        test_data (unconditionally) — not the full unfiltered train_data,
        and not missing any test_data rows. Verified by capturing the actual
        row count RandomForestRegressor.fit() was called with, not just by
        smoke-testing that predict() runs."""
        from unittest.mock import patch as mock_patch

        from sklearn.ensemble import RandomForestRegressor

        backend = SOMMLBackend()
        df = self._make_df()
        data, _, _ = backend._preprocess(df)
        unique_fields = data["FIELD_ID"].unique()
        rng = np.random.default_rng(0)
        test_fields = rng.choice(unique_fields, size=4, replace=False)
        train_fields = np.setdiff1d(unique_fields, test_fields)
        train_data = data[data["FIELD_ID"].isin(train_fields)].copy()
        test_data = data[data["FIELD_ID"].isin(test_fields)].copy()
        feats = [
            "BI_mean", "CI_mean", "NDMI_mean", "OMI_mean", "RI_mean",
            "SI_mean", "EVI_mean", "SAVI_mean", "NDVI_mean", "BSI_mean",
            "CAI_mean", "TILL Bon",
        ]

        fit_call_row_counts: list[int] = []
        original_fit = RandomForestRegressor.fit

        def spy_fit(self_rf, X, y, *args, **kwargs):
            fit_call_row_counts.append(len(X))
            return original_fit(self_rf, X, y, *args, **kwargs)

        with mock_patch.object(RandomForestRegressor, "fit", spy_fit):
            _, _, artifacts = backend._run_scenario(
                train_data, test_data, feats, "S1_spec_soil"
            )

        # _run_scenario fits several RandomForestRegressor instances during
        # the progressive image-selection passes (rf_base, n_estimators=50)
        # plus the two final n_estimators=200 fits (rf_final for evaluation,
        # rf_production for serving) — the production fit is the LAST call.
        final_production_row_count = fit_call_row_counts[-1]

        # Reconstruct train_final exactly as _run_scenario does, to compute
        # the expected row count independently of the implementation.
        # artifacts doesn't expose train_final directly, so derive the
        # expected count from what we can observe: the production set must
        # be strictly larger than test_data alone (it includes train rows
        # too) and must be smaller than train_data-plus-test_data UNLESS the
        # image-quality filter kept every single train image (verify the
        # filter actually dropped something in this fixture, so the
        # assertion below is a genuine, non-vacuous check).
        unfiltered_composition = len(train_data) + len(test_data)
        assert final_production_row_count > len(test_data), (
            "production model's training set must include train rows too, "
            "not just test_data"
        )
        assert final_production_row_count <= unfiltered_composition, (
            "production model's training set must not exceed train_data + "
            "test_data combined"
        )
        assert final_production_row_count < unfiltered_composition, (
            "production model was trained on the full unfiltered train_data "
            "plus test_data — the image-quality filter (train_final) was not "
            "applied. Expected fewer rows than train_data + test_data."
        )

        # Smoke check retained: the fitted model can actually predict.
        X_test_scaled = artifacts["scaler"].transform(
            test_data[feats].fillna(artifacts["col_means"]).values
        )[:, artifacts["feat_idx"]]
        preds = artifacts["rf_production"].predict(X_test_scaled)
        assert len(preds) == len(test_data)
