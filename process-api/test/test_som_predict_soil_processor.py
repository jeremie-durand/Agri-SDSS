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
    def _mock_bundle(self, scenario: str = "S1_spec_soil"):
        from unittest.mock import MagicMock

        bundle = MagicMock()
        bundle.scenario = scenario
        bundle.global_metrics = {
            "Scenario": scenario,
            "Algo": "RandomForest",
            "n_images_used": 5,
            "n_fields": 4,
            "val_r2": 0.8,
            "MAE_log": 0.08,
            "RMSE_log": 0.1,
            "R2_log": 0.9,
            "MAE_lin": 0.4,
            "RMSE_lin": 0.5,
            "R2_lin": 0.85,
            "r2_source": "test",
        }
        return bundle

    def test_returns_geojson_feature_collection(self):
        proc = _make_processor()
        preds = _minimal_preds_df().to_dict(orient="records")
        bundle = self._mock_bundle()

        with patch.object(
            proc, "_load_features_from_duckdb", return_value=_minimal_feature_df()
        ), patch.object(
            proc._model_store, "get_or_train", return_value=bundle
        ), patch.object(
            proc._model_store, "predict", return_value=preds
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
        assert len(fc["features"]) == len(preds)

    def test_field_summary_comes_from_bundle_global_metrics_unmodified(self):
        proc = _make_processor()
        preds = _minimal_preds_df().to_dict(orient="records")
        bundle = self._mock_bundle()

        with patch.object(
            proc, "_load_features_from_duckdb", return_value=_minimal_feature_df()
        ), patch.object(
            proc._model_store, "get_or_train", return_value=bundle
        ), patch.object(
            proc._model_store, "predict", return_value=preds
        ), patch.object(
            proc, "_fetch_field_geometries", return_value={416: None}
        ):

            _, result = proc.execute(
                {"field_ids": [416], "scenarios": ["S1_spec_soil"]}
            )

        assert result["value"]["field_summary"] == [bundle.global_metrics]

    def test_model_store_get_or_train_called_once_per_scenario(self):
        proc = _make_processor()
        preds = _minimal_preds_df().to_dict(orient="records")
        bundle = self._mock_bundle()

        with patch.object(
            proc, "_load_features_from_duckdb", return_value=_minimal_feature_df()
        ), patch.object(
            proc._model_store, "get_or_train", return_value=bundle
        ) as mock_get_or_train, patch.object(
            proc._model_store, "predict", return_value=preds
        ), patch.object(
            proc, "_fetch_field_geometries", return_value={416: None}
        ):

            proc.execute({"field_ids": [416], "scenarios": ["S1_spec_soil"]})

        mock_get_or_train.assert_called_once()
        assert mock_get_or_train.call_args.args[0] == "S1_spec_soil"

    def test_multi_scenario_request_calls_get_or_train_once_per_scenario(self):
        proc = _make_processor()
        preds = _minimal_preds_df().to_dict(orient="records")
        bundle_s1 = self._mock_bundle("S1_spec_soil")
        bundle_s2 = self._mock_bundle("S2_spec_soil_topo")

        def fake_get_or_train(scenario, all_data, data_dir):
            return bundle_s1 if scenario == "S1_spec_soil" else bundle_s2

        with patch.object(
            proc, "_load_features_from_duckdb", return_value=_minimal_feature_df()
        ), patch.object(
            proc._model_store, "get_or_train", side_effect=fake_get_or_train
        ) as mock_get_or_train, patch.object(
            proc._model_store, "predict", return_value=preds
        ), patch.object(
            proc, "_fetch_field_geometries", return_value={416: None}
        ):

            _, result = proc.execute(
                {
                    "field_ids": [416],
                    "scenarios": ["S1_spec_soil", "S2_spec_soil_topo"],
                }
            )

        assert mock_get_or_train.call_count == 2
        called_scenarios = {c.args[0] for c in mock_get_or_train.call_args_list}
        assert called_scenarios == {"S1_spec_soil", "S2_spec_soil_topo"}
        assert len(result["value"]["field_summary"]) == 2

    def test_one_scenario_failing_does_not_discard_another_scenarios_results(self):
        """If one requested scenario fails (e.g. insufficient data, or a
        predict()-time schema-drift error), the whole request must not be
        aborted if at least one other scenario succeeded — matching the old
        SOMMLBackend.run()'s per-scenario fault isolation this refactor must
        not silently drop."""
        proc = _make_processor()
        preds = _minimal_preds_df().to_dict(orient="records")
        bundle_s2 = self._mock_bundle("S2_spec_soil_topo")

        def fake_get_or_train(scenario, all_data, data_dir):
            if scenario == "S1_spec_soil":
                raise ValueError("S1_spec_soil has insufficient labeled data")
            return bundle_s2

        with patch.object(
            proc, "_load_features_from_duckdb", return_value=_minimal_feature_df()
        ), patch.object(
            proc._model_store, "get_or_train", side_effect=fake_get_or_train
        ), patch.object(
            proc._model_store, "predict", return_value=preds
        ), patch.object(
            proc, "_fetch_field_geometries", return_value={416: None}
        ):

            _, result = proc.execute(
                {
                    "field_ids": [416],
                    "scenarios": ["S1_spec_soil", "S2_spec_soil_topo"],
                }
            )

        # S1 failed, but S2 succeeded — the response must still contain S2's
        # results, not raise/discard everything.
        assert len(result["value"]["field_summary"]) == 1
        assert result["value"]["field_summary"][0]["Scenario"] == "S2_spec_soil_topo"
        assert len(result["value"]["features"]) == len(preds)

    def test_all_scenarios_failing_raises_processor_execute_error(self):
        proc = _make_processor()

        with patch.object(
            proc, "_load_features_from_duckdb", return_value=_minimal_feature_df()
        ), patch.object(
            proc._model_store,
            "get_or_train",
            side_effect=ValueError("no data for any scenario"),
        ), patch.object(
            proc, "_fetch_field_geometries", return_value={416: None}
        ):

            with pytest.raises(ProcessorExecuteError, match="No predictions"):
                proc.execute(
                    {
                        "field_ids": [416],
                        "scenarios": ["S1_spec_soil", "S2_spec_soil_topo"],
                    }
                )

    def test_feature_properties_shape(self):
        proc = _make_processor()
        preds = _minimal_preds_df().to_dict(orient="records")
        bundle = self._mock_bundle()

        with patch.object(
            proc, "_load_features_from_duckdb", return_value=_minimal_feature_df()
        ), patch.object(
            proc._model_store, "get_or_train", return_value=bundle
        ), patch.object(
            proc._model_store, "predict", return_value=preds
        ), patch.object(
            proc, "_fetch_field_geometries", return_value={416: None}
        ):

            _, result = proc.execute(
                {"field_ids": [416], "scenarios": ["S1_spec_soil"]}
            )

        feature = result["value"]["features"][0]
        props = feature["properties"]
        for key in (
            "FIELD_ID", "Image_ID", "y_true_lin", "y_pred_lin",
            "y_true_log", "y_pred_log", "algo", "scenario",
        ):
            assert key in props, f"Missing property: {key}"
