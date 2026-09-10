"""SOM Soil Prediction OGC API Process.

Queries DuckDB for GEE-derived SOM features, runs the RandomForest pipeline,
fetches field polygons from PostGIS, and returns a GeoJSON FeatureCollection.
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import duckdb
import pandas as pd
import psycopg
from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError

from .config import DatabaseConfig, StorageConfig
from .som_backend.som_ml_backend import BARESAIL_GLOB, SOMMLBackend
from .som_backend.som_model_store import SOMModelStore
from .som_predict_soil_metadata import PROCESS_METADATA

logger = logging.getLogger(__name__)


def _sanitize_nan(obj: Any) -> Any:
    """Recursively replace float NaN/Inf with None so the response is valid JSON."""
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _sanitize_nan(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_nan(v) for v in obj]
    return obj


class SOMPredictSoilProcessor(BaseProcessor):
    """OGC API Process: predict Soil Organic Matter for selected field IDs."""

    def __init__(self, processor_def: Dict[str, Any]) -> None:
        super().__init__(processor_def, PROCESS_METADATA)
        self._ml_backend = SOMMLBackend()
        model_dir = Path(StorageConfig().DUCKDB_DATA_DIR) / "som_models"
        self._model_store = SOMModelStore(self._ml_backend, model_dir)

    def execute(
        self, data: Dict[str, Any], outputs: Optional[Any] = None
    ) -> Tuple[str, Dict[str, Any]]:
        """Execute the SOM prediction process.

        Args:
            data: OGC process input dict with ``field_ids`` and optional ``scenarios``.
            outputs: Ignored (sync-execute only).

        Returns:
            Tuple of ("application/geo+json", {"id": "result", "value": <GeoJSON>}).

        Raises:
            ProcessorExecuteError: On invalid inputs or backend failure.
        """
        try:
            field_ids, scenarios = self._validate_inputs(data)
            all_data = self._load_features_from_duckdb(field_ids)
            data_dir = Path(StorageConfig().DUCKDB_DATA_DIR)

            requested = {float(fid) for fid in field_ids}
            requested_data = all_data[all_data["FIELD_ID"].isin(requested)]

            all_preds: List[Dict[str, Any]] = []
            field_summary: List[Dict[str, Any]] = []
            for scenario in scenarios:
                try:
                    bundle = self._model_store.get_or_train(
                        scenario, all_data, data_dir
                    )
                    preds = self._model_store.predict(bundle, requested_data)
                except Exception as exc:
                    logger.error(
                        "Scenario %s failed: %s", scenario, exc, exc_info=True
                    )
                    continue
                all_preds.extend(preds)
                field_summary.append(bundle.global_metrics)

            if not all_preds:
                raise ProcessorExecuteError(
                    "No predictions were produced. Check that the requested field IDs "
                    "have sufficient training data in the GEE feature Parquet files."
                )
            preds_df = pd.DataFrame(all_preds)
            geom_map = self._fetch_field_geometries(field_ids)
            feature_collection = self._build_feature_collection(
                preds_df, geom_map, field_summary
            )
            return "application/geo+json", {
                "id": "result",
                "value": _sanitize_nan(feature_collection),
            }

        except ProcessorExecuteError:
            raise
        except Exception as exc:
            logger.error(
                "Unexpected error in SOMPredictSoilProcessor: %s", exc, exc_info=True
            )
            raise ProcessorExecuteError(f"Unexpected error: {exc}") from exc

    # ------------------------------------------------------------------
    # Input validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_inputs(
        data: Dict[str, Any],
    ) -> Tuple[List[int], List[str]]:
        """Validate and extract field_ids and scenarios from raw input dict."""
        field_ids = data.get("field_ids")
        if not field_ids:
            raise ProcessorExecuteError(
                "'field_ids' is required and must contain at least one integer field ID."
            )
        try:
            field_ids = [int(fid) for fid in field_ids]
        except (TypeError, ValueError) as exc:
            raise ProcessorExecuteError(
                f"'field_ids' must be a list of integers: {exc}"
            ) from exc

        valid_scenarios = {
            "S1_spec_soil",
            "S2_spec_soil_topo",
            "S3_spec_soil_topo_clim",
        }
        scenarios = data.get("scenarios") or list(valid_scenarios)
        invalid = [s for s in scenarios if s not in valid_scenarios]
        if invalid:
            raise ProcessorExecuteError(
                f"Unknown scenarios: {invalid}. "
                f"Valid values: {sorted(valid_scenarios)}"
            )
        return field_ids, scenarios

    # ------------------------------------------------------------------
    # DuckDB feature loading
    # ------------------------------------------------------------------

    def _load_features_from_duckdb(self, field_ids: List[int]) -> pd.DataFrame:
        """Query all BareSoil_TOPCLI_*.parquet files in DUCKDB_DATA_DIR for the given field IDs.

        Args:
            field_ids: List of FIELD_ID integer values to filter.

        Returns:
            DataFrame with GEE feature rows for the requested fields.

        Raises:
            ProcessorExecuteError: If no Parquet files found or no rows match.
        """
        data_dir = Path(StorageConfig().DUCKDB_DATA_DIR)
        parquet_files = list(data_dir.glob(BARESAIL_GLOB))
        if not parquet_files:
            raise ProcessorExecuteError(
                "No GEE feature Parquet files found. "
                "Run the gis-pipeline to ingest the BareSoil_TOPCLI_*.csv files first."
            )

        glob_pattern = str(data_dir / BARESAIL_GLOB)
        # Load all labeled data (needed for training, if a cache miss occurs
        # downstream in SOMModelStore). This only confirms at least one
        # requested field has SOME row in the raw Parquet data — the real
        # prediction-time filtering (missing mean_SOM, outlier bounds) happens
        # later in SOMMLBackend.preprocess_for_predict(), called from
        # SOMModelStore.predict().
        # union_by_name=true handles schema differences across yearly CSV exports
        query = f"SELECT * FROM read_parquet('{glob_pattern}', union_by_name=true)"

        try:
            con = duckdb.connect()
            df = con.execute(query).df()
            con.close()
        except duckdb.Error as exc:
            raise ProcessorExecuteError(
                f"Failed to query GEE feature Parquet files: {exc}"
            ) from exc

        if df.empty:
            raise ProcessorExecuteError(
                "GEE feature Parquet files are empty. "
                "Run the gis-pipeline to ingest the BareSoil_TOPCLI_*.csv files."
            )

        df["FIELD_ID"] = df["FIELD_ID"].astype(float)
        requested = {float(fid) for fid in field_ids}
        if not df["FIELD_ID"].isin(requested).any():
            raise ProcessorExecuteError(
                f"No feature data found for field IDs {field_ids} "
                "in the GEE feature Parquet files."
            )
        logger.info(
            "Loaded %d rows for %d field IDs from DuckDB.",
            len(df),
            df["FIELD_ID"].nunique(),
        )
        return df

    # ------------------------------------------------------------------
    # PostGIS geometry fetch
    # ------------------------------------------------------------------

    def _fetch_field_geometries(self, field_ids: List[int]) -> Dict[int, Any]:
        """Query som_field_boundaries for Polygon geometries by FIELD_ID (= gid).

        Args:
            field_ids: List of field IDs to look up.

        Returns:
            Dict mapping FIELD_ID → GeoJSON geometry dict (or None if not found).
        """
        conn_params = DatabaseConfig().to_conn_params()
        sql = (
            "SELECT gid, ST_AsGeoJSON(geometry)::text AS geom_json "
            "FROM som_field_boundaries WHERE gid = ANY(%s)"
        )
        geom_map: Dict[int, Any] = {fid: None for fid in field_ids}
        try:
            with psycopg.connect(**conn_params) as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, (field_ids,))
                    for gid, geom_json in cur.fetchall():
                        geom_map[int(gid)] = (
                            json.loads(geom_json) if geom_json else None
                        )
        except psycopg.Error as exc:
            logger.warning(
                "Could not fetch field geometries from PostGIS: %s. "
                "Returning null geometries.",
                exc,
            )

        missing = [fid for fid, geom in geom_map.items() if geom is None]
        if missing:
            logger.warning(
                "No geometry found in som_field_boundaries for field IDs: %s", missing
            )
        return geom_map

    # ------------------------------------------------------------------
    # GeoJSON assembly
    # ------------------------------------------------------------------

    @staticmethod
    def _build_feature_collection(
        preds_df: pd.DataFrame,
        geom_map: Dict[int, Any],
        field_metrics: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Assemble a GeoJSON FeatureCollection from image-level predictions.

        Args:
            preds_df: DataFrame of image-level prediction rows.
            geom_map: FIELD_ID → GeoJSON geometry dict.
            field_metrics: List of field-level metric dicts for the field_summary key.

        Returns:
            GeoJSON FeatureCollection dict.
        """
        features = []
        for _, row in preds_df.iterrows():
            field_id = int(row["FIELD_ID"])
            features.append(
                {
                    "type": "Feature",
                    "geometry": geom_map.get(field_id),
                    "properties": {
                        "row_id": int(row.get("row_id", 0)),
                        "FIELD_ID": field_id,
                        "Image_ID": str(row["Image_ID"]),
                        "y_true_lin": float(row["y_true_lin"]),
                        "y_pred_lin": float(row["y_pred_lin"]),
                        "y_true_log": float(row["y_true_log"]),
                        "y_pred_log": float(row["y_pred_log"]),
                        "algo": str(row["algo"]),
                        "scenario": str(row["scenario"]),
                    },
                }
            )
        return {
            "type": "FeatureCollection",
            "field_summary": field_metrics,
            "features": features,
        }

    def __repr__(self) -> str:
        return f"<SOMPredictSoilProcessor> {self.name}"
