"""Persisted model store for som-predict-soil.

Decouples the expensive training pipeline (LassoCV feature selection,
per-image ranking, progressive RF selection, final RF fit — collectively
~200s per scenario) from serving predictions. A trained bundle is persisted
to disk per scenario and reused across requests until the underlying
training data changes (detected via a cheap file-stat fingerprint).
"""

from __future__ import annotations

import hashlib
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import pandas as pd
import sklearn
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import MultiLabelBinarizer, StandardScaler

from .som_ml_backend import BARESAIL_GLOB, SOMMLBackend

logger = logging.getLogger(__name__)


@dataclass
class SOMModelBundle:
    """A trained, ready-to-serve model for one scenario."""

    scenario: str
    scaler: StandardScaler
    selected_features: list[str]
    feat_idx: list[int]
    col_means: pd.Series
    mlb: MultiLabelBinarizer
    log_som_bounds: tuple[float, float]
    rf_production: RandomForestRegressor
    smearing_factor: float
    global_metrics: dict[str, Any]
    fingerprint: str
    trained_at: str
    sklearn_version: str


def compute_fingerprint(data_dir: Path) -> str:
    """SHA-256 hash of (filename, mtime, size) for every
    BareSoil_TOPCLI_*.parquet file in data_dir — cheap (stat only, no file
    reads) and changes whenever training data is added, removed, or
    modified."""
    parquet_files = sorted(data_dir.glob(BARESAIL_GLOB))
    stats = [(f.name, f.stat().st_mtime_ns, f.stat().st_size) for f in parquet_files]
    return hashlib.sha256(repr(stats).encode()).hexdigest()


def _is_undefined(value: Any) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


class SOMModelStore:
    """Loads a cached, trained model bundle per scenario, or trains and
    persists a new one when missing or the training data has changed.

    Concurrency assumption (not enforced in code): process-api runs gunicorn
    with the default sync worker class and WEB_CONCURRENCY unset (a single
    worker process handling one request at a time), so two requests can't
    race to train the same scenario concurrently. If WEB_CONCURRENCY or the
    worker class ever changes for process-api, this needs revisiting — e.g.
    a file lock around the train-and-persist path in get_or_train().

    Sklearn version tracking: each bundle records the scikit-learn version it
    was trained under (SOMModelBundle.sklearn_version). A mismatch on load is
    logged as a WARNING rather than forcing a retrain — sklearn's own
    InconsistentVersionWarning is suppressed process-wide by
    som_ml_backend.py's warnings.filterwarnings() call, so this is the only
    signal that would otherwise exist after a dependency bump changes the
    pickled model's compatibility.
    """

    def __init__(self, ml_backend: SOMMLBackend, model_dir: Path) -> None:
        self._ml_backend = ml_backend
        self._model_dir = model_dir

    def _bundle_path(self, scenario: str) -> Path:
        return self._model_dir / f"som_model_{scenario}.joblib"

    def get_or_train(
        self, scenario: str, all_data: pd.DataFrame, data_dir: Path
    ) -> SOMModelBundle:
        """Return a valid cached bundle for `scenario`, training and
        persisting a fresh one if missing or the training data has changed
        since it was last trained."""
        fingerprint = compute_fingerprint(data_dir)
        bundle_path = self._bundle_path(scenario)

        if bundle_path.exists():
            try:
                bundle: SOMModelBundle = joblib.load(bundle_path)
                if bundle.fingerprint == fingerprint:
                    if bundle.sklearn_version != sklearn.__version__:
                        logger.warning(
                            "Cached model for scenario '%s' was trained under "
                            "scikit-learn %s, but %s is installed now. "
                            "Predictions may be affected by the version "
                            "mismatch (sklearn's own compatibility warnings "
                            "are suppressed process-wide by som_ml_backend.py, "
                            "so this log line is the only signal). Delete "
                            "%s to force a retrain if this is a concern.",
                            scenario,
                            bundle.sklearn_version,
                            sklearn.__version__,
                            bundle_path,
                        )
                    logger.info(
                        "Cache hit: reusing trained model for scenario '%s'",
                        scenario,
                    )
                    return bundle
                logger.info(
                    "Training data changed for scenario '%s' (fingerprint "
                    "mismatch) — retraining.",
                    scenario,
                )
            except Exception as exc:
                logger.warning(
                    "Could not load cached model bundle at %s: %s — retraining.",
                    bundle_path,
                    exc,
                )

        bundle = self._train(scenario, all_data, fingerprint)
        self._persist(bundle, bundle_path)
        return bundle

    def _train(
        self, scenario: str, all_data: pd.DataFrame, fingerprint: str
    ) -> SOMModelBundle:
        result = self._ml_backend.run(
            all_data, scenarios=[scenario], target_field_ids=None
        )
        artifacts = result.get("artifacts", {}).get(scenario)
        if artifacts is None:
            raise ValueError(
                f"Training produced no artifacts for scenario {scenario!r} — "
                "check that the scenario has sufficient labeled data."
            )
        metrics_list = [m for m in result["metrics"] if m["scenario"] == scenario]
        if not metrics_list:
            raise ValueError(f"Training produced no metrics for scenario {scenario!r}.")
        summary = metrics_list[0]

        r2_undefined = _is_undefined(summary["R2_lin"])
        global_metrics: dict[str, Any] = {
            "Scenario": scenario,
            "Algo": "RandomForest",
            "n_images_used": summary["n_images_used"],
            "n_fields": artifacts["n_test_fields"],
            "val_r2": summary["val_r2"],
            "MAE_log": summary["MAE_log"],
            "RMSE_log": summary["RMSE_log"],
            "R2_log": summary["R2_log"],
            "MAE_lin": summary["MAE_lin"],
            "RMSE_lin": summary["RMSE_lin"],
            "R2_lin": summary["val_r2"] if r2_undefined else summary["R2_lin"],
            "r2_source": "val" if r2_undefined else "test",
        }

        return SOMModelBundle(
            scenario=scenario,
            scaler=artifacts["scaler"],
            selected_features=artifacts["selected_features"],
            feat_idx=artifacts["feat_idx"],
            col_means=artifacts["col_means"],
            mlb=result["mlb"],
            log_som_bounds=result["log_som_bounds"],
            rf_production=artifacts["rf_production"],
            smearing_factor=artifacts["smearing_factor"],
            global_metrics=global_metrics,
            fingerprint=fingerprint,
            trained_at=datetime.now(timezone.utc).isoformat(),
            sklearn_version=sklearn.__version__,
        )

    @staticmethod
    def _persist(bundle: SOMModelBundle, bundle_path: Path) -> None:
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = bundle_path.with_suffix(".tmp")
        joblib.dump(bundle, tmp_path)
        tmp_path.replace(bundle_path)

    def predict(
        self, bundle: SOMModelBundle, field_raw_df: pd.DataFrame
    ) -> list[dict[str, Any]]:
        """Fast prediction for the given raw (unprocessed) feature rows,
        using an already-loaded bundle — no training involved."""
        data = self._ml_backend.preprocess_for_predict(
            field_raw_df, bundle.mlb, bundle.log_som_bounds
        )
        if data.empty:
            return []

        missing_cols = [c for c in bundle.col_means.index if c not in data.columns]
        if missing_cols:
            raise ValueError(
                f"Cannot predict for scenario {bundle.scenario!r}: the input "
                f"data is missing columns the model was trained on: "
                f"{missing_cols}. This usually means the source Parquet "
                "schema changed since this model was trained — delete the "
                "cached bundle to force a retrain against the new schema."
            )
        X = bundle.scaler.transform(
            data[bundle.col_means.index].fillna(bundle.col_means).values
        )[:, bundle.feat_idx]
        y_pred_log = bundle.rf_production.predict(X)
        y_pred_lin = (10.0**y_pred_log) * bundle.smearing_factor

        preds: list[dict[str, Any]] = []
        for i, (idx, row) in enumerate(data.iterrows()):
            preds.append(
                {
                    "row_id": int(idx),
                    "FIELD_ID": int(row["FIELD_ID"]),
                    "Image_ID": str(row["Image_ID"]),
                    "y_true_lin": float(10.0 ** row["log_SOM"]),
                    "y_pred_lin": float(y_pred_lin[i]),
                    "y_true_log": float(row["log_SOM"]),
                    "y_pred_log": float(y_pred_log[i]),
                    "algo": "RandomForest",
                    "scenario": bundle.scenario,
                }
            )
        return preds
