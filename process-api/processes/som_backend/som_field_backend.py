"""SOM field-level aggregation backend.

Wraps the field-level aggregation logic (originally field_level_analysis.py
by Hamed Etezadi) as a callable class.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, r2_score, root_mean_squared_error

logger = logging.getLogger(__name__)

_REQUIRED_COLS = {
    "FIELD_ID",
    "Image_ID",
    "y_true_log",
    "y_pred_log",
    "y_true_lin",
    "y_pred_lin",
    "algo",
    "scenario",
}


def field_level_from_preds(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate image-level predictions to field-level means per (algo, scenario, FIELD_ID)."""
    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        raise KeyError(f"Missing columns in predictions DataFrame: {missing}")
    return df.groupby(["algo", "scenario", "FIELD_ID"], as_index=False).agg(
        y_true_log_field=("y_true_log", "mean"),
        y_pred_log_field=("y_pred_log", "mean"),
        y_true_lin_field=("y_true_lin", "mean"),
        y_pred_lin_field=("y_pred_lin", "mean"),
        n_images=("Image_ID", "nunique"),
    )


def _safe_r2(y_true: Any, y_pred: Any) -> float:
    """Return r2_score, or NaN when fewer than 2 unique true values (undefined)."""
    import numpy as np

    if len(np.unique(y_true)) < 2:
        return float("nan")
    return float(r2_score(y_true, y_pred))


def metrics_per_group(fld: pd.DataFrame) -> pd.DataFrame:
    """Compute RMSE/MAE/R² on field-level aggregated predictions per (algo, scenario)."""
    rows = []
    for (algo, scen), g in fld.groupby(["algo", "scenario"]):
        rows.append(
            {
                "Algo": algo,
                "Scenario": scen,
                "RMSE_log": float(
                    root_mean_squared_error(
                        g["y_true_log_field"], g["y_pred_log_field"]
                    )
                ),
                "MAE_log": float(
                    mean_absolute_error(g["y_true_log_field"], g["y_pred_log_field"])
                ),
                "R2_log": _safe_r2(g["y_true_log_field"], g["y_pred_log_field"]),
                "RMSE_lin": float(
                    root_mean_squared_error(
                        g["y_true_lin_field"], g["y_pred_lin_field"]
                    )
                ),
                "MAE_lin": float(
                    mean_absolute_error(g["y_true_lin_field"], g["y_pred_lin_field"])
                ),
                "R2_lin": _safe_r2(g["y_true_lin_field"], g["y_pred_lin_field"]),
                "n_fields": int(g["FIELD_ID"].nunique()),
                "avg_images_per_field": float(g["n_images"].mean()),
            }
        )
    return pd.DataFrame(rows)


class SOMFieldBackend:
    """Aggregates image-level SOM predictions to field-level metrics."""

    def run(self, predictions_df: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
        """Aggregate predictions to field level.

        Args:
            predictions_df: DataFrame with columns matching _REQUIRED_COLS.

        Returns:
            {"field_predictions": [...], "field_metrics": [...]}
        """
        fld = field_level_from_preds(predictions_df)
        summary = metrics_per_group(fld)

        field_predictions = [
            {
                "FIELD_ID": int(row["FIELD_ID"]),
                "algo": str(row["algo"]),
                "scenario": str(row["scenario"]),
                "y_true_log_field": float(row["y_true_log_field"]),
                "y_pred_log_field": float(row["y_pred_log_field"]),
                "y_true_lin_field": float(row["y_true_lin_field"]),
                "y_pred_lin_field": float(row["y_pred_lin_field"]),
                "n_images": int(row["n_images"]),
            }
            for _, row in fld.iterrows()
        ]
        field_metrics = [
            {
                k: (float(v) if isinstance(v, (np.floating, float)) else v)
                for k, v in row.items()
            }
            for row in summary.to_dict(orient="records")
        ]
        return {"field_predictions": field_predictions, "field_metrics": field_metrics}
