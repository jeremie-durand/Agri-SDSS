"""SOM Soil Prediction OGC API Process.

Takes som_field_boundaries gids, or a location resolved to the GEE fields that
som-field-match finds there. Resolves those gids to their GEE FIELD_IDs and
polygons in PostGIS, queries DuckDB for the GEE-derived SOM features of those
FIELD_IDs, runs the RandomForest pipeline, and returns a GeoJSON
FeatureCollection.
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

from agri_i18n import _

from .config import DatabaseConfig, StorageConfig
from .som_backend.som_ml_backend import BARESAIL_GLOB, SOMMLBackend
from .som_backend.som_model_store import SOMModelStore
from .som_predict_soil_metadata import PROCESS_METADATA
from .spatial_backend import (
    DEFAULT_TOLERANCE_M,
    SpatialLocationInput,
    match_som_fields,
    parse_inputs,
    prepare_geometry,
)

logger = logging.getLogger(__name__)

_LOCATION_KEYS: tuple[str, ...] = (
    "location_type",
    "farm_id",
    "point",
    "polygon",
    "bbox",
)


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
            data: OGC process input dict with ``field_ids`` or a location, and
                optional ``scenarios``.
            outputs: Ignored (sync-execute only).

        Returns:
            Tuple of ("application/geo+json", {"id": "result", "value": <GeoJSON>}).

        Raises:
            ProcessorExecuteError: On invalid inputs or backend failure.
        """
        try:
            field_ids, location, scenarios = self._validate_inputs(data)
            gids = field_ids if location is None else self._gids_at_location(location)
            fields = self._resolve_fields(gids)
            gee_field_ids = sorted(field_id for field_id, _geom in fields.values())
            all_data = self._load_features_from_duckdb(gee_field_ids, sorted(fields))
            data_dir = Path(StorageConfig().DUCKDB_DATA_DIR)

            requested = {float(fid) for fid in gee_field_ids}
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
                    logger.error("Scenario %s failed: %s", scenario, exc, exc_info=True)
                    continue
                all_preds.extend(preds)
                field_summary.append(bundle.global_metrics)

            if not all_preds:
                raise ProcessorExecuteError(
                    _(
                        "No predictions were produced. Check that the requested "
                        "field IDs have sufficient training data in the GEE "
                        "feature Parquet files."
                    )
                )
            preds_df = pd.DataFrame(all_preds)
            by_field_id = {
                field_id: (gid, geom) for gid, (field_id, geom) in fields.items()
            }
            feature_collection = self._build_feature_collection(
                preds_df, by_field_id, field_summary
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
            raise ProcessorExecuteError(
                _("An unexpected error occurred while running this process.")
            ) from exc

    # ------------------------------------------------------------------
    # Input validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_inputs(
        data: Dict[str, Any],
    ) -> tuple[list[int] | None, SpatialLocationInput | None, list[str]]:
        """Validate and extract field_ids or a location, and scenarios.

        Exactly one of the returned field_ids and location is set.
        """
        location_data = {key: data[key] for key in _LOCATION_KEYS if key in data}
        field_ids = data.get("field_ids")
        location: SpatialLocationInput | None = None
        if location_data:
            if "field_ids" in data:
                raise ProcessorExecuteError(
                    _("Send either 'field_ids' or a location, not both.")
                )
            location = parse_inputs(SpatialLocationInput, location_data)
        elif not field_ids:
            raise ProcessorExecuteError(
                _(
                    "'field_ids' is required and must contain at least one "
                    "integer field ID."
                )
            )
        else:
            try:
                field_ids = [int(fid) for fid in field_ids]
            except (TypeError, ValueError) as exc:
                raise ProcessorExecuteError(
                    _("'field_ids' must be a list of integers: {error}").format(
                        error=exc
                    )
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
                _("Unknown scenarios: {invalid}. Valid values: {valid}").format(
                    invalid=invalid, valid=sorted(valid_scenarios)
                )
            )
        return field_ids, location, scenarios

    @staticmethod
    def _gids_at_location(location: SpatialLocationInput) -> list[int]:
        """Return the gids with GEE data that som-field-match finds at *location*.

        Raises:
            ProcessorExecuteError: If no matched field has GEE data.
        """
        matches = match_som_fields(prepare_geometry(location), DEFAULT_TOLERANCE_M)
        gids = [m["gid"] for m in matches if m["has_gee_data"]]
        if not gids:
            raise ProcessorExecuteError(
                _("No SOM field with GEE training data was found at this location.")
            )
        return gids

    # ------------------------------------------------------------------
    # DuckDB feature loading
    # ------------------------------------------------------------------

    def _load_features_from_duckdb(
        self, field_ids: List[int], reported_ids: list[int] | None = None
    ) -> pd.DataFrame:
        """Query all BareSoil_TOPCLI_*.parquet files in DUCKDB_DATA_DIR for the given field IDs.

        Args:
            field_ids: List of FIELD_ID integer values to filter.
            reported_ids: IDs named in the error message when no row matches;
                the caller's gids, since GEE FIELD_IDs mean nothing to them.
                Defaults to field_ids.

        Returns:
            DataFrame with GEE feature rows for the requested fields.

        Raises:
            ProcessorExecuteError: If no Parquet files found or no rows match.
        """
        data_dir = Path(StorageConfig().DUCKDB_DATA_DIR)
        parquet_files = list(data_dir.glob(BARESAIL_GLOB))
        if not parquet_files:
            raise ProcessorExecuteError(
                _(
                    "No GEE feature Parquet files found. Run the gis-pipeline to "
                    "ingest the BareSoil_TOPCLI_*.csv files first."
                )
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
            logger.error(
                "DuckDB query on GEE feature Parquet files failed: %s",
                exc,
                exc_info=True,
            )
            raise ProcessorExecuteError(
                _("Could not read the GEE feature data.")
            ) from exc

        if df.empty:
            raise ProcessorExecuteError(
                _(
                    "GEE feature Parquet files are empty. Run the gis-pipeline to "
                    "ingest the BareSoil_TOPCLI_*.csv files."
                )
            )

        df["FIELD_ID"] = df["FIELD_ID"].astype(float)
        requested = {float(fid) for fid in field_ids}
        if not df["FIELD_ID"].isin(requested).any():
            raise ProcessorExecuteError(
                _(
                    "No feature data found for field IDs {field_ids} in the GEE "
                    "feature Parquet files."
                ).format(field_ids=reported_ids or field_ids)
            )
        logger.info(
            "Loaded %d rows for %d field IDs from DuckDB.",
            len(df),
            df["FIELD_ID"].nunique(),
        )
        return df

    # ------------------------------------------------------------------
    # PostGIS field resolution
    # ------------------------------------------------------------------

    def _resolve_fields(self, gids: list[int]) -> dict[int, tuple[int, Any]]:
        """Map requested som_field_boundaries gids to GEE FIELD_IDs and polygons.

        The platform gid and the GEE FIELD_ID are different identifiers;
        gis-pipeline stores the FIELD_ID of each GEE field in gee_field_id.
        Requested gids without a gee_field_id are logged and left out.

        Args:
            gids: som_field_boundaries gid values sent by the caller.

        Returns:
            Dict mapping gid → (GEE FIELD_ID, GeoJSON geometry dict or None).

        Raises:
            ProcessorExecuteError: If PostGIS cannot be queried, or if none of
                the requested gids has GEE data.
        """
        conn_params = DatabaseConfig().to_conn_params()
        sql = (
            "SELECT gid, gee_field_id, ST_AsGeoJSON(geometry)::text AS geom_json "
            "FROM som_field_boundaries "
            "WHERE gid = ANY(%s) AND gee_field_id IS NOT NULL"
        )
        fields: dict[int, tuple[int, Any]] = {}
        try:
            with psycopg.connect(**conn_params) as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, (gids,))
                    for gid, field_id, geom_json in cur.fetchall():
                        fields[int(gid)] = (
                            int(field_id),
                            json.loads(geom_json) if geom_json else None,
                        )
        except psycopg.Error as exc:
            logger.error(
                "Could not resolve SOM fields from PostGIS: %s", exc, exc_info=True
            )
            raise ProcessorExecuteError(
                _("Could not read the SOM field boundaries.")
            ) from exc

        if not fields:
            raise ProcessorExecuteError(
                _("None of the field IDs {field_ids} has GEE training data.").format(
                    field_ids=gids
                )
            )
        missing = sorted(set(gids) - fields.keys())
        if missing:
            logger.warning("Field IDs without GEE data were skipped: %s", missing)
        return fields

    # ------------------------------------------------------------------
    # GeoJSON assembly
    # ------------------------------------------------------------------

    @staticmethod
    def _build_feature_collection(
        preds_df: pd.DataFrame,
        by_field_id: dict[int, tuple[int, Any]],
        field_metrics: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Assemble a GeoJSON FeatureCollection from image-level predictions.

        Args:
            preds_df: DataFrame of image-level prediction rows.
            by_field_id: GEE FIELD_ID → (gid, GeoJSON geometry dict or None).
            field_metrics: List of field-level metric dicts for the field_summary key.

        Returns:
            GeoJSON FeatureCollection dict.
        """
        features = []
        for _idx, row in preds_df.iterrows():
            field_id = int(row["FIELD_ID"])
            gid, geometry = by_field_id.get(field_id, (None, None))
            features.append(
                {
                    "type": "Feature",
                    "geometry": geometry,
                    "properties": {
                        "row_id": int(row.get("row_id", 0)),
                        "gid": gid,
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
