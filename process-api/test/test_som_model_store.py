"""Unit tests for the SOM model store (train-once, serve-fast caching)."""

from __future__ import annotations

import json
import math
import multiprocessing
import os
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest
from process_api.test.som_lock_helpers import train_scenario
from processes.som_backend.som_ml_backend import SOMMLBackend
from processes.som_backend.som_model_store import (
    SOMModelBundle,
    SOMModelStore,
    compute_fingerprint,
)


def _make_df(n_fields: int = 20, n_images_per_field: int = 5) -> pd.DataFrame:
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


@pytest.mark.unit
class TestComputeFingerprint:
    def test_stable_when_files_unchanged(self, tmp_path):
        (tmp_path / "BareSoil_TOPCLI_2019_Part01.parquet").write_bytes(b"abc")
        fp1 = compute_fingerprint(tmp_path)
        fp2 = compute_fingerprint(tmp_path)
        assert fp1 == fp2

    def test_changes_when_a_file_is_modified(self, tmp_path):
        f = tmp_path / "BareSoil_TOPCLI_2019_Part01.parquet"
        f.write_bytes(b"abc")
        fp1 = compute_fingerprint(tmp_path)
        f.write_bytes(b"a different, longer payload")
        fp2 = compute_fingerprint(tmp_path)
        assert fp1 != fp2

    def test_changes_when_a_file_is_added(self, tmp_path):
        (tmp_path / "BareSoil_TOPCLI_2019_Part01.parquet").write_bytes(b"abc")
        fp1 = compute_fingerprint(tmp_path)
        (tmp_path / "BareSoil_TOPCLI_2020_Part01.parquet").write_bytes(b"def")
        fp2 = compute_fingerprint(tmp_path)
        assert fp1 != fp2

    def test_unchanged_when_only_the_modification_time_changes(
        self, tmp_path: Path
    ) -> None:
        f = tmp_path / "BareSoil_TOPCLI_2019_Part01.parquet"
        f.write_bytes(b"abc")
        fp1 = compute_fingerprint(tmp_path)
        os.utime(f, ns=(1_000_000_000, 1_000_000_000))
        fp2 = compute_fingerprint(tmp_path)
        assert fp1 == fp2

    def test_same_files_copied_elsewhere_give_the_same_fingerprint(
        self, tmp_path: Path
    ) -> None:
        source = tmp_path / "source"
        copy = tmp_path / "copy"
        source.mkdir()
        copy.mkdir()
        for name, payload in (
            ("BareSoil_TOPCLI_2019_Part01.parquet", b"abc"),
            ("BareSoil_TOPCLI_2020_Part01.parquet", b"def"),
        ):
            (source / name).write_bytes(payload)
        for f in source.iterdir():
            (copy / f.name).write_bytes(f.read_bytes())
            os.utime(copy / f.name, ns=(2_000_000_000, 2_000_000_000))
        assert compute_fingerprint(source) == compute_fingerprint(copy)

    def test_independent_of_the_order_files_are_listed_in(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "BareSoil_TOPCLI_2019_Part01.parquet").write_bytes(b"abc")
        (tmp_path / "BareSoil_TOPCLI_2020_Part01.parquet").write_bytes(b"def")
        fp1 = compute_fingerprint(tmp_path)
        listed = Path.glob

        def reversed_glob(self: Path, pattern: str) -> list[Path]:
            return list(listed(self, pattern))[::-1]

        monkeypatch.setattr(Path, "glob", reversed_glob)
        fp2 = compute_fingerprint(tmp_path)
        assert fp1 == fp2

    def test_changes_when_content_changes_with_same_size_and_mtime(
        self, tmp_path: Path
    ) -> None:
        f = tmp_path / "BareSoil_TOPCLI_2019_Part01.parquet"
        f.write_bytes(b"abc")
        os.utime(f, ns=(1_000_000_000, 1_000_000_000))
        fp1 = compute_fingerprint(tmp_path)
        f.write_bytes(b"xyz")
        os.utime(f, ns=(1_000_000_000, 1_000_000_000))
        fp2 = compute_fingerprint(tmp_path)
        assert fp1 != fp2


@pytest.mark.mocked
class TestSOMModelStoreGetOrTrain:
    def test_trains_and_persists_on_first_call(self, tmp_path):
        model_dir = tmp_path / "som_models"
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "BareSoil_TOPCLI_2019_Part01.parquet").write_bytes(b"abc")

        store = SOMModelStore(SOMMLBackend(), model_dir)
        df = _make_df()

        bundle = store.get_or_train("S1_spec_soil", df, data_dir)

        assert isinstance(bundle, SOMModelBundle)
        assert bundle.scenario == "S1_spec_soil"
        assert (model_dir / "som_model_S1_spec_soil.joblib").exists()
        assert not (model_dir / "som_model_S1_spec_soil.tmp").exists()

    def test_second_call_with_unchanged_fingerprint_does_not_retrain(
        self, tmp_path, monkeypatch
    ):
        model_dir = tmp_path / "som_models"
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "BareSoil_TOPCLI_2019_Part01.parquet").write_bytes(b"abc")

        real_backend = SOMMLBackend()
        store = SOMModelStore(real_backend, model_dir)
        df = _make_df()

        store.get_or_train("S1_spec_soil", df, data_dir)

        spy = MagicMock(wraps=real_backend.run)
        monkeypatch.setattr(real_backend, "run", spy)
        bundle2 = store.get_or_train("S1_spec_soil", df, data_dir)
        spy.assert_not_called()

        assert bundle2.scenario == "S1_spec_soil"

    def test_stale_fingerprint_triggers_retrain(self, tmp_path, monkeypatch):
        model_dir = tmp_path / "som_models"
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "BareSoil_TOPCLI_2019_Part01.parquet").write_bytes(b"abc")

        real_backend = SOMMLBackend()
        store = SOMModelStore(real_backend, model_dir)
        df = _make_df()

        first_bundle = store.get_or_train("S1_spec_soil", df, data_dir)

        (data_dir / "BareSoil_TOPCLI_2019_Part01.parquet").write_bytes(
            b"a different payload changes the content hash"
        )

        spy = MagicMock(wraps=real_backend.run)
        monkeypatch.setattr(real_backend, "run", spy)
        second_bundle = store.get_or_train("S1_spec_soil", df, data_dir)
        spy.assert_called_once()

        assert first_bundle.fingerprint != second_bundle.fingerprint

    def test_bundle_trained_on_a_copy_of_the_same_files_is_reused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        model_dir = tmp_path / "som_models"
        trained_on = tmp_path / "trained_on"
        served_from = tmp_path / "served_from"
        trained_on.mkdir()
        served_from.mkdir()
        (trained_on / "BareSoil_TOPCLI_2019_Part01.parquet").write_bytes(b"abc")

        real_backend = SOMMLBackend()
        store = SOMModelStore(real_backend, model_dir)
        df = _make_df()
        store.get_or_train("S1_spec_soil", df, trained_on)

        downloaded = served_from / "BareSoil_TOPCLI_2019_Part01.parquet"
        downloaded.write_bytes(b"abc")
        os.utime(downloaded, ns=(2_000_000_000, 2_000_000_000))

        spy = MagicMock(wraps=real_backend.run)
        monkeypatch.setattr(real_backend, "run", spy)
        store.get_or_train("S1_spec_soil", df, served_from)
        spy.assert_not_called()

    def test_corrupt_bundle_on_disk_triggers_retrain_with_warning(
        self, tmp_path, caplog
    ):
        model_dir = tmp_path / "som_models"
        model_dir.mkdir()
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "BareSoil_TOPCLI_2019_Part01.parquet").write_bytes(b"abc")
        (model_dir / "som_model_S1_spec_soil.joblib").write_bytes(
            b"not a valid joblib file"
        )

        store = SOMModelStore(SOMMLBackend(), model_dir)
        df = _make_df()

        import logging

        with caplog.at_level(logging.WARNING):
            bundle = store.get_or_train("S1_spec_soil", df, data_dir)

        assert isinstance(bundle, SOMModelBundle)
        assert any(
            "Could not load cached model bundle" in record.message
            for record in caplog.records
        )

    def test_sklearn_version_mismatch_logs_warning_on_cache_hit(self, tmp_path, caplog):
        import logging

        import joblib

        model_dir = tmp_path / "som_models"
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "BareSoil_TOPCLI_2019_Part01.parquet").write_bytes(b"abc")

        store = SOMModelStore(SOMMLBackend(), model_dir)
        df = _make_df()
        bundle = store.get_or_train("S1_spec_soil", df, data_dir)

        # Tamper the persisted bundle's sklearn_version to simulate a
        # dependency bump since training, then re-save it in place.
        bundle_path = model_dir / "som_model_S1_spec_soil.joblib"
        bundle.sklearn_version = "0.0.1-fake"
        joblib.dump(bundle, bundle_path)

        with caplog.at_level(logging.WARNING):
            reloaded = store.get_or_train("S1_spec_soil", df, data_dir)

        assert reloaded.sklearn_version == "0.0.1-fake"  # cache hit, not retrained
        assert any(
            "scikit-learn 0.0.1-fake" in record.message for record in caplog.records
        )

    def test_matching_sklearn_version_does_not_log_warning(self, tmp_path, caplog):
        import logging

        model_dir = tmp_path / "som_models"
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "BareSoil_TOPCLI_2019_Part01.parquet").write_bytes(b"abc")

        store = SOMModelStore(SOMMLBackend(), model_dir)
        df = _make_df()
        store.get_or_train("S1_spec_soil", df, data_dir)

        with caplog.at_level(logging.WARNING):
            store.get_or_train("S1_spec_soil", df, data_dir)

        assert not any(
            "scikit-learn" in record.message and "installed now" in record.message
            for record in caplog.records
        )

    def test_training_failure_does_not_leave_partial_bundle(self, tmp_path):
        model_dir = tmp_path / "som_models"
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "BareSoil_TOPCLI_2019_Part01.parquet").write_bytes(b"abc")

        broken_backend = MagicMock()
        broken_backend.run.side_effect = RuntimeError("boom")
        store = SOMModelStore(broken_backend, model_dir)

        with pytest.raises(RuntimeError):
            store.get_or_train("S1_spec_soil", _make_df(), data_dir)

        assert not (model_dir / "som_model_S1_spec_soil.joblib").exists()
        assert not any(model_dir.glob("*.tmp")) if model_dir.exists() else True


@pytest.mark.mocked
class TestSOMModelStorePredict:
    def test_predict_returns_rows_for_requested_field(self, tmp_path):
        model_dir = tmp_path / "som_models"
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "BareSoil_TOPCLI_2019_Part01.parquet").write_bytes(b"abc")

        store = SOMModelStore(SOMMLBackend(), model_dir)
        df = _make_df()
        bundle = store.get_or_train("S1_spec_soil", df, data_dir)

        field_0_raw = df[df["FIELD_ID"] == 0.0]
        preds = store.predict(bundle, field_0_raw)

        assert len(preds) > 0
        for pred in preds:
            assert pred["FIELD_ID"] == 0
            for key in (
                "row_id",
                "Image_ID",
                "y_true_lin",
                "y_pred_lin",
                "y_true_log",
                "y_pred_log",
                "algo",
                "scenario",
            ):
                assert key in pred

    def test_predict_empty_input_returns_empty_list(self, tmp_path):
        model_dir = tmp_path / "som_models"
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "BareSoil_TOPCLI_2019_Part01.parquet").write_bytes(b"abc")

        store = SOMModelStore(SOMMLBackend(), model_dir)
        df = _make_df()
        bundle = store.get_or_train("S1_spec_soil", df, data_dir)

        empty = df.iloc[0:0]
        assert store.predict(bundle, empty) == []

    def test_predict_missing_column_raises_clear_error(self, tmp_path):
        model_dir = tmp_path / "som_models"
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "BareSoil_TOPCLI_2019_Part01.parquet").write_bytes(b"abc")

        store = SOMModelStore(SOMMLBackend(), model_dir)
        df = _make_df()
        bundle = store.get_or_train("S1_spec_soil", df, data_dir)

        field_0_raw = df[df["FIELD_ID"] == 0.0].drop(columns=["BI_mean"])

        with pytest.raises(ValueError, match="missing columns"):
            store.predict(bundle, field_0_raw)

    def test_predict_serves_grouped_cv_values_for_known_fields(self, tmp_path):
        """A training field is answered by a fold RandomForest that never saw it."""
        model_dir = tmp_path / "som_models"
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "BareSoil_TOPCLI_2019_Part01.parquet").write_bytes(b"abc")

        store = SOMModelStore(SOMMLBackend(), model_dir)
        df = _make_df()
        bundle = store.get_or_train("S1_spec_soil", df, data_dir)

        preds = store.predict(bundle, df[df["FIELD_ID"] == 0.0])

        assert preds
        for pred in preds:
            key = (pred["FIELD_ID"], pred["Image_ID"])
            assert pred["y_pred_log"] == pytest.approx(bundle.cv_predictions[key])

    def test_v2_bundle_is_retrained(self, tmp_path):
        """v2 bundles carry out-of-bag predictions and must not be served."""
        import joblib

        model_dir = tmp_path / "som_models"
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "BareSoil_TOPCLI_2019_Part01.parquet").write_bytes(b"abc")

        store = SOMModelStore(SOMMLBackend(), model_dir)
        df = _make_df()
        bundle = store.get_or_train("S1_spec_soil", df, data_dir)
        bundle.format_version = 2
        joblib.dump(bundle, store._bundle_path("S1_spec_soil"))

        original_train = store._train
        calls: list[str] = []

        def spy_train(scenario, all_data, fingerprint):
            calls.append(scenario)
            return original_train(scenario, all_data, fingerprint)

        store._train = spy_train
        retrained = store.get_or_train("S1_spec_soil", df, data_dir)

        assert calls == ["S1_spec_soil"]
        assert retrained.format_version == 3


@pytest.mark.unit
class TestGlobalMetricsShape:
    def test_global_metrics_has_frontend_required_keys(self, tmp_path):
        model_dir = tmp_path / "som_models"
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "BareSoil_TOPCLI_2019_Part01.parquet").write_bytes(b"abc")

        store = SOMModelStore(SOMMLBackend(), model_dir)
        bundle = store.get_or_train("S1_spec_soil", _make_df(), data_dir)

        for key in (
            "Scenario",
            "Algo",
            "n_images_used",
            "n_fields",
            "val_r2",
            "MAE_log",
            "RMSE_log",
            "R2_log",
            "MAE_lin",
            "RMSE_lin",
            "R2_lin",
            "r2_source",
        ):
            assert key in bundle.global_metrics, f"Missing key: {key}"
        assert bundle.global_metrics["r2_source"] in ("test", "val")
        r2 = bundle.global_metrics["R2_lin"]
        assert r2 is None or not (isinstance(r2, float) and math.isnan(r2))


def _run_concurrently(
    tmp_path: Path, scenarios: list[str], delay: float
) -> tuple[list[dict], list[dict]]:
    model_dir = tmp_path / "som_models"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "BareSoil_TOPCLI_2019_Part01.parquet").write_bytes(b"abc")
    runs_log = tmp_path / "runs.jsonl"
    ctx = multiprocessing.get_context("spawn")
    results = [tmp_path / f"result_{i}.json" for i in range(len(scenarios))]
    start_together = ctx.Barrier(len(scenarios))
    children = [
        ctx.Process(
            target=train_scenario,
            args=(
                str(model_dir),
                str(data_dir),
                scenario,
                str(runs_log),
                str(result),
                delay,
                start_together,
            ),
        )
        for scenario, result in zip(scenarios, results)
    ]
    try:
        for child in children:
            child.start()
        for child in children:
            child.join(timeout=120)
    finally:
        for child in children:
            if child.is_alive():
                child.kill()
                child.join()
    assert [child.exitcode for child in children] == [0] * len(children)
    runs = [json.loads(line) for line in runs_log.read_text().splitlines()]
    return runs, [json.loads(result.read_text()) for result in results]


@pytest.mark.unit
class TestSOMModelStoreConcurrency:
    def test_same_scenario_trains_once_across_processes(self, tmp_path):
        runs, results = _run_concurrently(
            tmp_path, ["S3_spec_soil_topo_clim", "S3_spec_soil_topo_clim"], 2.0
        )

        assert len(runs) == 1
        assert results[0] == results[1]

    def test_different_scenarios_train_in_parallel(self, tmp_path):
        runs, _ = _run_concurrently(
            tmp_path, ["S1_spec_soil", "S2_spec_soil_topo"], 2.0
        )

        assert len(runs) == 2
        first, second = sorted(runs, key=lambda run: run["start"])
        assert second["start"] < first["end"]
