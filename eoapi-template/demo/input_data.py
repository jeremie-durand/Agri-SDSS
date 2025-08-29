# eoapi-template/demo/input_data.py
import logging
from pathlib import Path
from typing import List, Tuple

import geopandas as gpd
import sqlalchemy

from demo.init_postgis import read_data_postgis
from demo.util import add_process_to_logger

logger = logging.getLogger(__name__)


def handle_postgis(
    engine: sqlalchemy.engine.Engine, tables: List[str]
) -> List[Tuple[str, gpd.GeoDataFrame]]:
    """Read vector tables from PostGIS.

    Args:
        engine: SQLAlchemy engine connected to the PostGIS database.
        tables: List of table names to read.

    Returns:
        List of tuples, each containing the table name and its corresponding GeoDataFrame.
    """
    if engine is None:
        raise ValueError("Engine must be provided for local PostGIS connection.")

    data_list = []
    for table in tables:
        gdf = read_data_postgis(engine, table)
        logger.info(
            f"Vector data read from PostGIS table: {table} ({len(gdf)} features)"
        )
        data_list.append((table, gdf))
    return data_list


def vector_data_acquisition(
    input_source: str, tables: List[str], engine: sqlalchemy.engine.Engine = None
) -> List[Tuple[str, gpd.GeoDataFrame]]:
    """Acquire vector data from various sources.

    Args:
        input_source: Source type ('postgis', 'duckdb', 'local', 'remote')
        tables: List of table names for PostGIS (or other sources in future)
        engine: SQLAlchemy engine for PostGIS connection

    Returns:
        List of tuples, each tuple includes two items (table_name, GeoDataFrame).
    """
    match input_source.lower():
        case "postgis":
            add_process_to_logger(logger, "PostGIS data acquisition")
            return handle_postgis(engine, tables)
        case "duckdb":
            add_process_to_logger(logger, "DuckDB data acquisition")
            return []
        case "local":
            add_process_to_logger(logger, "Local data acquisition")
            return []
        case "remote":
            add_process_to_logger(logger, "Remote data acquisition")
            return []
        case _:
            logger.error(
                f"Unknown input source: {input_source}. Choose from 'postgis', 'duckdb', 'local', 'remote'."
            )
            raise ValueError(f"Unknown input source: {input_source}")


def list_local_raster_files(raster_path: Path) -> List[Path]:
    """List all raster files in a directory, excluding COGs.

    Args:
        raster_path: Path to the directory containing raster files

    Returns:
        List of raster Paths (excluding COGs)
    """
    add_process_to_logger(logger, "Local raster file acquisition")
    if not raster_path.exists():
        logger.warning(f"Raster directory does not exist: {raster_path}")
        return []

    sources = [
        f for f in raster_path.iterdir() if f.suffix.lower() in (".tif", ".tiff")
    ]

    is_raster_files_exist = [
        f for f in sources
        if not any([
            f.name.lower().endswith("_cog.tif"),
            f.name.lower().endswith("_cog.tiff")
        ])
    ]

    if not is_raster_files_exist:
        logger.warning(f"No raster files found in {raster_path} or all files are COGs.")
    else:
        logger.info(
            f"Found {len(is_raster_files_exist)} raster file(s) to process: {[f.name for f in is_raster_files_exist]}"
        )

    return is_raster_files_exist
