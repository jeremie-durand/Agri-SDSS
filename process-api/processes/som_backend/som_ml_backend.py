"""SOM image-level ML backend.

Wraps the RandomForest SOM prediction pipeline (originally machine_learning_image_level.py
by Hamed Etezadi, updated to Jadid-30Jan2026 algorithm) as a callable class. Accepts a
pre-loaded feature DataFrame and returns JSON-serialisable prediction and metric dicts.
"""

from __future__ import annotations

import logging
import warnings
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import Lasso, LassoCV
from sklearn.metrics import (
    mean_absolute_error,
    r2_score,
    root_mean_squared_error,
)
from sklearn.model_selection import GroupKFold, GroupShuffleSplit
from sklearn.preprocessing import MultiLabelBinarizer, StandardScaler

logger = logging.getLogger(__name__)

warnings.filterwarnings("ignore", category=ConvergenceWarning)
warnings.filterwarnings("ignore", category=UserWarning, module="sklearn")

RANDOM_STATE = 42
TEST_FIELD_RATIO = 0.2
DROP_THRESHOLD = 0.01
MIN_INNER_TRAIN_ROWS = 30
MIN_IMAGE_ROWS = 10

SPECTRAL_MEANS = [
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
]
SPECTRAL_STDS = [
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
]
TOPO_COLS = ["elevation_mean", "slope_mean", "aspect_mean"]
CLIM_COLS = ["BIO1_mean", "BIO12_mean"]
BASE_COLS = ["FIELD_ID", "Image_ID", "mean_SOM", "soilTypes"]


def parse_soil_list(s: Any) -> list[str]:
    """Parse a soil type string like '[TILL Bon, SABLE Mauvais]' into a list."""
    s = str(s).strip("[]").replace("'", "")
    return [t.strip() for t in s.split(",") if t.strip()]


class SOMMLBackend:
    """RandomForest SOM image-level prediction pipeline (Jadid-30Jan2026 algorithm)."""

    def run(
        self,
        data_df: pd.DataFrame,
        scenarios: list[str] | None = None,
        show_plots: bool = False,
        target_field_ids: list[int] | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """Run the full SOM prediction pipeline on the supplied feature DataFrame.

        Args:
            data_df: DataFrame with ALL available training data (all GEE fields).
            scenarios: Scenario keys to run. Defaults to all three.
            show_plots: Unused (kept for API compatibility).
            target_field_ids: If provided, these field IDs become the test set and
                all other fields are used for training. Enables predictions for
                specific user-selected farms. If None, a random 20% split is used.

        Returns:
            {"predictions": [...], "metrics": [...]}
        """
        if scenarios is None:
            scenarios = ["S1_spec_soil", "S2_spec_soil_topo", "S3_spec_soil_topo_clim"]

        missing_base = [c for c in BASE_COLS if c not in data_df.columns]
        if missing_base:
            raise ValueError(f"Missing required columns: {missing_base}")

        missing_spectral = [
            c for c in SPECTRAL_MEANS + SPECTRAL_STDS if c not in data_df.columns
        ]
        if missing_spectral:
            raise ValueError(f"Missing spectral columns: {missing_spectral}")

        data = data_df.dropna(subset=["mean_SOM"]).copy()

        # Outlier removal on log10(mean_SOM) via IQR
        log_som = np.log10(data["mean_SOM"])
        q1, q3 = log_som.quantile(0.25), log_som.quantile(0.75)
        iqr = q3 - q1
        data = data[(log_som >= q1 - 1.5 * iqr) & (log_som <= q3 + 1.5 * iqr)].copy()
        data["log_SOM"] = np.log10(data["mean_SOM"])

        # soilTypes → one-hot
        data["soilTypes_parsed"] = data["soilTypes"].apply(parse_soil_list)
        mlb = MultiLabelBinarizer()
        soil_features = mlb.fit_transform(data["soilTypes_parsed"])
        soil_feature_names = mlb.classes_.tolist()
        soil_df = pd.DataFrame(
            soil_features, columns=soil_feature_names, index=data.index
        )
        data = pd.concat([data, soil_df], axis=1)

        spectral_cols = SPECTRAL_MEANS + SPECTRAL_STDS
        present_topo = [c for c in TOPO_COLS if c in data.columns]
        present_clim = [c for c in CLIM_COLS if c in data.columns]

        scenario_features: dict[str, list[str]] = {
            "S1_spec_soil": spectral_cols + soil_feature_names,
            "S2_spec_soil_topo": spectral_cols + soil_feature_names + present_topo,
            "S3_spec_soil_topo_clim": spectral_cols
            + soil_feature_names
            + present_topo
            + present_clim,
        }

        unique_fields = data["FIELD_ID"].unique()
        if target_field_ids:
            target_as_float = [float(fid) for fid in target_field_ids]
            test_fields = np.array(
                [fid for fid in target_as_float if fid in unique_fields]
            )
            if len(test_fields) == 0:
                raise ValueError(
                    f"None of the requested field IDs {target_field_ids} have GEE data."
                )
            train_fields = np.setdiff1d(unique_fields, test_fields)
        else:
            rng = np.random.default_rng(RANDOM_STATE)
            n_test = max(1, int(TEST_FIELD_RATIO * len(unique_fields)))
            test_fields = rng.choice(unique_fields, size=n_test, replace=False)
            train_fields = np.setdiff1d(unique_fields, test_fields)

        train_data = data[data["FIELD_ID"].isin(train_fields)].copy()
        test_data = data[data["FIELD_ID"].isin(test_fields)].copy()

        all_summaries: list[dict[str, Any]] = []
        all_preds: list[dict[str, Any]] = []

        for scenario_tag in scenarios:
            if scenario_tag not in scenario_features:
                logger.warning("Unknown scenario %s — skipping.", scenario_tag)
                continue
            feats = [c for c in scenario_features[scenario_tag] if c in data.columns]
            if len(feats) < 2:
                logger.warning(
                    "Scenario %s has too few features — skipping.", scenario_tag
                )
                continue

            try:
                summary, preds = self._run_scenario(
                    train_data, test_data, feats, scenario_tag
                )
                all_summaries.append(summary)
                all_preds.extend(preds)
            except Exception as exc:
                logger.error("Scenario %s failed: %s", scenario_tag, exc, exc_info=True)

        return {"predictions": all_preds, "metrics": all_summaries}

    def _run_scenario(
        self,
        train_data: pd.DataFrame,
        test_data: pd.DataFrame,
        independent_vars: list[str],
        scenario_tag: str,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Jadid algorithm: inner-split LassoCV FS → GroupKFold image ranking → val-based best_i → final RF."""
        col_means = train_data[independent_vars].mean()

        X_train_raw = train_data[independent_vars].fillna(col_means).values
        y_train = train_data["log_SOM"].values
        g_train = train_data["FIELD_ID"].values

        X_test_raw = test_data[independent_vars].fillna(col_means).values
        y_test = test_data["log_SOM"].values
        y_test_lin = 10.0**y_test

        # Inner split: GroupShuffleSplit by FIELD_ID (20% inner-val)
        n_unique_train = len(np.unique(g_train))
        if n_unique_train >= 3:
            gss = GroupShuffleSplit(
                n_splits=1, test_size=0.2, random_state=RANDOM_STATE
            )
            inner_tr_idx, inner_val_idx = next(gss.split(X_train_raw, y_train, g_train))
        else:
            # Degenerate case: use full train as both inner-train and inner-val
            inner_tr_idx = np.arange(len(X_train_raw))
            inner_val_idx = np.arange(len(X_train_raw))

        X_tr_in_raw = X_train_raw[inner_tr_idx]
        y_tr_in = y_train[inner_tr_idx]

        X_val_in_raw = X_train_raw[inner_val_idx]
        y_val_in = y_train[inner_val_idx]

        inner_train_df = train_data.iloc[inner_tr_idx].reset_index(drop=True)

        # Scaler fit on inner-train only
        scaler = StandardScaler()
        X_tr_in = scaler.fit_transform(X_tr_in_raw)
        X_val_in = scaler.transform(X_val_in_raw)
        X_test_sc = scaler.transform(X_test_raw)

        # LassoCV feature selection on inner-train only
        lasso_cv = LassoCV(cv=5, random_state=RANDOM_STATE, max_iter=100000, n_jobs=1)
        lasso_cv.fit(X_tr_in, y_tr_in)
        coef = pd.Series(lasso_cv.coef_, index=independent_vars)
        selected = coef[coef != 0]
        if selected.empty:
            selected = coef.abs().sort_values(ascending=False).head(10)
        selected_features = selected.index.tolist()
        feat_idx = [independent_vars.index(f) for f in selected_features]

        # Image ranking with fixed Lasso alpha + GroupKFold on inner-train
        lasso_fixed = Lasso(alpha=lasso_cv.alpha_, max_iter=100000)
        image_scores: list[dict[str, Any]] = []

        for img_id, df_img in inner_train_df.groupby("Image_ID"):
            if df_img.shape[0] < MIN_IMAGE_ROWS:
                continue
            X_img = scaler.transform(df_img[independent_vars].fillna(col_means).values)[
                :, feat_idx
            ]
            y_img = df_img["log_SOM"].values
            g_img = df_img["FIELD_ID"].values

            n_splits = max(2, min(3, len(np.unique(g_img))))
            cv_rmse: list[float] = []
            for tr_i, va_i in GroupKFold(n_splits=n_splits).split(
                X_img, y_img, groups=g_img
            ):
                lasso_fixed.fit(X_img[tr_i], y_img[tr_i])
                pred = lasso_fixed.predict(X_img[va_i])
                cv_rmse.append(float(root_mean_squared_error(y_img[va_i], pred)))

            image_scores.append(
                {
                    "Image_ID": img_id,
                    "CV_RMSE": float(np.mean(cv_rmse)),
                    "n": int(df_img.shape[0]),
                }
            )

        if not image_scores:
            # Fallback: use all images unranked (happens with very small datasets)
            image_scores = [
                {"Image_ID": i, "CV_RMSE": 0.0, "n": 0}
                for i in inner_train_df["Image_ID"].unique()
            ]

        ranked_images = (
            pd.DataFrame(image_scores).sort_values("CV_RMSE").reset_index(drop=True)
        )

        # Progressive RF on inner-val (no test leakage)
        # n_estimators=50: these fits are for ranking/selection only, not final prediction
        rf_base = RandomForestRegressor(
            n_estimators=50, random_state=RANDOM_STATE, n_jobs=1
        )
        val_results: list[dict[str, Any]] = []

        for i in range(1, len(ranked_images) + 1):
            selected_ids = ranked_images.iloc[:i]["Image_ID"].tolist()
            tr_scn = inner_train_df[inner_train_df["Image_ID"].isin(selected_ids)]
            if tr_scn.shape[0] < MIN_INNER_TRAIN_ROWS:
                continue
            X_tr_scn = scaler.transform(
                tr_scn[independent_vars].fillna(col_means).values
            )[:, feat_idx]
            rf_base.fit(X_tr_scn, tr_scn["log_SOM"].values)
            pred_val = rf_base.predict(X_val_in[:, feat_idx])
            r2_val = (
                float(r2_score(y_val_in, pred_val))
                if len(np.unique(y_val_in)) >= 2
                else float("nan")
            )
            val_results.append(
                {
                    "Images_Used": i,
                    "R2_val": r2_val,
                    "img_id": ranked_images.iloc[i - 1]["Image_ID"],
                }
            )

        # Remove bad images via inner-val R² drop, then re-run to find best_i
        val_df = pd.DataFrame(val_results).reset_index(drop=True)
        bad_image_ids: set[str] = set()
        for k in range(1, len(val_df)):
            if val_df.loc[k, "R2_val"] < val_df.loc[k - 1, "R2_val"] - DROP_THRESHOLD:
                bad_image_ids.add(str(val_df.loc[k, "img_id"]))

        ranked_good = ranked_images[
            ~ranked_images["Image_ID"].isin(bad_image_ids)
        ].reset_index(drop=True)
        if ranked_good.empty:
            ranked_good = ranked_images.copy()

        val_good_results: list[dict[str, Any]] = []
        for i in range(1, len(ranked_good) + 1):
            selected_ids = ranked_good.iloc[:i]["Image_ID"].tolist()
            tr_scn = inner_train_df[inner_train_df["Image_ID"].isin(selected_ids)]
            if tr_scn.shape[0] < MIN_INNER_TRAIN_ROWS:
                continue
            X_tr_scn = scaler.transform(
                tr_scn[independent_vars].fillna(col_means).values
            )[:, feat_idx]
            rf_base.fit(X_tr_scn, tr_scn["log_SOM"].values)
            pred_val = rf_base.predict(X_val_in[:, feat_idx])
            r2_val = (
                float(r2_score(y_val_in, pred_val))
                if len(np.unique(y_val_in)) >= 2
                else float("nan")
            )
            val_good_results.append({"Images_Used": i, "R2_val": r2_val})

        if val_good_results:
            val_good_df = pd.DataFrame(val_good_results)
            best_idx = val_good_df["R2_val"].idxmax()
            best_i = int(val_good_df.loc[best_idx, "Images_Used"])
            best_val_r2 = float(val_good_df.loc[best_idx, "R2_val"])
        else:
            best_i = len(ranked_good)
            best_val_r2 = float("nan")

        selected_final_ids = ranked_good.iloc[:best_i]["Image_ID"].tolist()
        n_images_used = len(selected_final_ids)

        # Final model on full outer train with selected images
        train_final = train_data[train_data["Image_ID"].isin(selected_final_ids)]
        X_train_final = scaler.transform(
            train_final[independent_vars].fillna(col_means).values
        )[:, feat_idx]
        y_train_final = train_final["log_SOM"].values

        rf_final = RandomForestRegressor(
            n_estimators=200, random_state=RANDOM_STATE, n_jobs=1
        )
        rf_final.fit(X_train_final, y_train_final)

        # Duan smearing factor from training residuals
        y_train_pred = rf_final.predict(X_train_final)
        smearing_factor = float(np.mean(10.0 ** (y_train_final - y_train_pred)))

        # Evaluate once on test set
        X_test_final = X_test_sc[:, feat_idx]
        y_pred_log = rf_final.predict(X_test_final)
        y_pred_lin = (10.0**y_pred_log) * smearing_factor

        summary = {
            "scenario": scenario_tag,
            "algo": "RandomForest",
            "n_images_used": n_images_used,
            "val_r2": best_val_r2,
            "MAE_log": float(mean_absolute_error(y_test, y_pred_log)),
            "RMSE_log": float(root_mean_squared_error(y_test, y_pred_log)),
            "R2_log": float(r2_score(y_test, y_pred_log)),
            "MAE_lin": float(mean_absolute_error(y_test_lin, y_pred_lin)),
            "RMSE_lin": float(root_mean_squared_error(y_test_lin, y_pred_lin)),
            "R2_lin": float(r2_score(y_test_lin, y_pred_lin)),
        }

        preds = [
            {
                "row_id": int(idx),
                "FIELD_ID": int(row["FIELD_ID"]),
                "Image_ID": str(row["Image_ID"]),
                "y_true_lin": float(10.0 ** row["log_SOM"]),
                "y_pred_lin": float(y_pred_lin[i]),
                "y_true_log": float(row["log_SOM"]),
                "y_pred_log": float(y_pred_log[i]),
                "algo": "RandomForest",
                "scenario": scenario_tag,
            }
            for i, (idx, row) in enumerate(test_data.iterrows())
        ]

        return summary, preds
