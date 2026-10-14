"""Mocked integration tests for SOMPredictSoilProcessor."""

from unittest.mock import patch

import pandas as pd
import pytest
from processes.som_predict_soil import SOMPredictSoilProcessor
from pygeoapi.process.base import ProcessorExecuteError

import agri_i18n


@pytest.fixture(autouse=True)
def _english_messages():
    """Assert against the English msgids rather than the French default."""
    with agri_i18n.use_locale("en"):
        yield


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
                proc.execute({"field_ids": [195], "scenarios": ["invalid"]})

    def test_non_integer_field_ids_raises(self):
        proc = _make_processor()
        with pytest.raises(ProcessorExecuteError, match="integers"):
            proc.execute({"field_ids": ["not_an_int"]})


@pytest.mark.mocked
class TestSOMPredictSoilProcessorDuckDB:
    @pytest.fixture(autouse=True)
    def _resolved_field(self):
        with patch.object(
            SOMPredictSoilProcessor,
            "_resolve_fields",
            return_value={195: (416, None)},
        ):
            yield

    def test_missing_parquet_files_raises(self, tmp_path):
        proc = _make_processor()
        with patch.dict("os.environ", {"DUCKDB_DATA_DIR": str(tmp_path)}):
            with pytest.raises(ProcessorExecuteError, match="No GEE feature Parquet"):
                proc.execute({"field_ids": [195]})

    def test_duckdb_error_does_not_leak_internal_detail(self, tmp_path):
        """A DuckDB failure yields a generic message, not the raw driver error."""
        import duckdb

        proc = _make_processor()
        (tmp_path / "BareSoil_TOPCLI_2019_Part01.parquet").write_bytes(b"not parquet")
        with patch.dict("os.environ", {"DUCKDB_DATA_DIR": str(tmp_path)}), patch(
            "processes.som_predict_soil.duckdb.connect",
            side_effect=duckdb.Error("magic bytes 0xdeadbeef mismatch"),
        ):
            with pytest.raises(
                ProcessorExecuteError, match="Could not read the GEE feature data"
            ) as excinfo:
                proc.execute({"field_ids": [195]})

        assert "0xdeadbeef" not in str(
            excinfo.value
        ), "internal DuckDB error must not reach the user"

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
                proc.execute({"field_ids": [195]})


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
            proc, "_resolve_fields", return_value={195: (416, None)}
        ):

            mime, result = proc.execute(
                {"field_ids": [195], "scenarios": ["S1_spec_soil"]}
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
            proc, "_resolve_fields", return_value={195: (416, None)}
        ):

            _, result = proc.execute(
                {"field_ids": [195], "scenarios": ["S1_spec_soil"]}
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
            proc, "_resolve_fields", return_value={195: (416, None)}
        ):

            proc.execute({"field_ids": [195], "scenarios": ["S1_spec_soil"]})

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
            proc, "_resolve_fields", return_value={195: (416, None)}
        ):

            _, result = proc.execute(
                {
                    "field_ids": [195],
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
            proc, "_resolve_fields", return_value={195: (416, None)}
        ):

            _, result = proc.execute(
                {
                    "field_ids": [195],
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
            proc, "_resolve_fields", return_value={195: (416, None)}
        ):

            with pytest.raises(ProcessorExecuteError, match="No predictions"):
                proc.execute(
                    {
                        "field_ids": [195],
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
            proc, "_resolve_fields", return_value={195: (416, None)}
        ):

            _, result = proc.execute(
                {"field_ids": [195], "scenarios": ["S1_spec_soil"]}
            )

        feature = result["value"]["features"][0]
        props = feature["properties"]
        for key in (
            "gid",
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


def _mock_psycopg_rows(mock_connect, rows):
    conn = mock_connect.return_value.__enter__.return_value
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = rows
    return cursor


@pytest.mark.mocked
class TestSOMPredictSoilFieldResolution:
    """Requested gids are translated to GEE FIELD_IDs through gee_field_id."""

    @pytest.fixture(autouse=True)
    def _db_config(self):
        with patch("processes.som_predict_soil.DatabaseConfig"):
            yield

    def test_resolves_gid_to_field_id_and_geometry(self):
        proc = _make_processor()
        with patch("processes.som_predict_soil.psycopg.connect") as mock_connect:
            cursor = _mock_psycopg_rows(
                mock_connect, [(195, 416, '{"type": "Point", "coordinates": [0, 0]}')]
            )
            fields = proc._resolve_fields([195, 999])

        assert fields == {195: (416, {"type": "Point", "coordinates": [0, 0]})}
        sql, params = cursor.execute.call_args.args
        assert "gee_field_id IS NOT NULL" in sql
        assert params == ([195, 999],)

    def test_no_gid_with_gee_data_raises(self):
        proc = _make_processor()
        with patch("processes.som_predict_soil.psycopg.connect") as mock_connect:
            _mock_psycopg_rows(mock_connect, [])
            with pytest.raises(ProcessorExecuteError, match="has GEE training data"):
                proc._resolve_fields([999])

    def test_database_error_does_not_leak_internal_detail(self):
        import psycopg

        proc = _make_processor()
        with patch(
            "processes.som_predict_soil.psycopg.connect",
            side_effect=psycopg.OperationalError("password authentication failed"),
        ):
            with pytest.raises(
                ProcessorExecuteError, match="Could not read the SOM field boundaries"
            ) as excinfo:
                proc._resolve_fields([195])

        assert "password" not in str(excinfo.value)

    def test_execute_reads_gee_data_by_field_id_and_reports_gid(self):
        """The GEE data are filtered by FIELD_ID, never by the requested gid."""
        proc = _make_processor()
        preds = _minimal_preds_df().to_dict(orient="records")
        bundle = TestSOMPredictSoilProcessorHappyPath()._mock_bundle()
        geometry = {"type": "Point", "coordinates": [0, 0]}

        with patch.object(
            proc, "_resolve_fields", return_value={195: (416, geometry)}
        ), patch.object(
            proc, "_load_features_from_duckdb", return_value=_minimal_feature_df()
        ) as mock_load, patch.object(
            proc._model_store, "get_or_train", return_value=bundle
        ), patch.object(
            proc._model_store, "predict", return_value=preds
        ) as mock_predict:
            _, result = proc.execute(
                {"field_ids": [195], "scenarios": ["S1_spec_soil"]}
            )

        mock_load.assert_called_once_with([416], [195])
        predicted_fields = set(mock_predict.call_args.args[1]["FIELD_ID"])
        assert predicted_fields == {416.0}
        props = result["value"]["features"][0]["properties"]
        assert props["gid"] == 195
        assert props["FIELD_ID"] == 416
        assert result["value"]["features"][0]["geometry"] == geometry


@pytest.mark.mocked
def test_no_matching_rows_error_names_the_requested_gids(tmp_path):
    """The caller sent gid 195; GEE FIELD_ID 416 would mean nothing to them."""
    import duckdb

    proc = _make_processor()
    con = duckdb.connect()
    con.execute(
        f"COPY (SELECT 999.0 AS FIELD_ID, '2019_0505' AS Image_ID) "
        f"TO '{tmp_path}/BareSoil_TOPCLI_2019_Part01.parquet' (FORMAT PARQUET)"
    )
    con.close()
    with patch.dict("os.environ", {"DUCKDB_DATA_DIR": str(tmp_path)}):
        with pytest.raises(ProcessorExecuteError, match=r"\[195\]") as excinfo:
            proc._load_features_from_duckdb([416], [195])

    assert "416" not in str(excinfo.value)
