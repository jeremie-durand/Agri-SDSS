"""Trigger a spatial index rebuild after gis-pipeline writes a collection's
GeoParquet file, and notify vector-api to pick it up without a restart.

Never raises: this is an optimization layer, not core data ingestion. Any
failure here is logged and the pipeline continues -- mirrors how
StacApiClient's publish failures never abort a pipeline run
(modules/processing/processing_stac.py).
"""

from pathlib import Path

import requests
import structlog
from gis_pipeline.core.config import Config
from gis_pipeline.modules.db.materialize import materialize_collection

logger = structlog.get_logger()


def trigger_materialize_and_notify(table: str) -> None:
    """Rebuild table's persistent spatial index and notify vector-api.

    Args:
        table: Collection ID -- the Parquet filename stem that was just
            written by save_gdf_to_geoparquet() for this table.
    """
    if not Config.VECTOR_API_URL:
        logger.debug("materialize_trigger_skipped_no_vector_api_url", table=table)
        return

    data_dir = Path(Config.DUCKDB_DATA_DIR)
    parquet_path = data_dir / f"{table}.parquet"
    if not parquet_path.exists():
        logger.warning("materialize_trigger_parquet_missing", table=table)
        return

    final_path = data_dir / f"{table}.duckdb"
    new_path = data_dir / f"{table}.duckdb.new"
    new_wal_path = data_dir / f"{table}.duckdb.new.wal"

    try:
        new_path.unlink(missing_ok=True)
        new_wal_path.unlink(missing_ok=True)
        row_count = materialize_collection(parquet_path, new_path)
        new_path.rename(final_path)
    except Exception as exc:
        logger.warning(
            "materialize_trigger_build_failed", table=table, error=str(exc)
        )
        return

    logger.info("materialize_trigger_built", table=table, row_count=row_count)

    _notify_vector_api(table)


def _notify_vector_api(table: str) -> None:
    """Best-effort POST to vector-api's /invalidate endpoint. Never raises."""
    url = f"{Config.VECTOR_API_URL.rstrip('/')}/parquet/collections/{table}/invalidate"
    try:
        response = requests.post(url, timeout=10)
        response.raise_for_status()
        logger.info(
            "materialize_trigger_notified", table=table, response=response.json()
        )
    except (requests.RequestException, ConnectionError) as exc:
        logger.warning(
            "materialize_trigger_notify_failed", table=table, url=url, error=str(exc)
        )
