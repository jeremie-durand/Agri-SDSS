# eoapi-template/demo/main.py
"""
Main script to run the geoprocessing pipeline for vector and raster data.
"""
import logging

from demo.logging_setup import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

from pathlib import Path

from demo.config import Config
from demo.geoprocessing import (
    geoprocessing_raster_data_postgis,
    geoprocessing_vector_data_postgis,
)
from demo.init_postgis import connect_to_postgis
from demo.input_data import list_local_raster_files, vector_data_acquisition
from demo.util import generate_processing_report, add_section_to_logger


def main():
    """Main function to run the geoprocessing pipeline.

    This function orchestrates the entire geoprocessing workflow, including:
    - Setting up logging
    - Connecting to the PostGIS database
    - Connecting to the DuckDB database (to be implemented in the future)
    - Acquiring vector data from the specified source
    - Processing vector data (harmonizing, cleaning geometries, harmonizing CRS)
    - Inserting processed vector data into database and posting to STAC API
    - Processing raster data (to be implemented in the future)
    - Inserting processed raster data into database and posting to STAC API
    - Generating a processing report
    """
    add_section_to_logger(logger, "EOAPI Geoprocessing Pipeline")
    report_data = {
        "vector_data": {"processed": 0, "errors": 0, "skipped": 0},
        "raster_data": {"processed": 0, "errors": 0, "skipped": 0},
    }

    add_section_to_logger(logger, "Connecting to PostGIS")
    engine_postgis = connect_to_postgis(
        user=Config.POSTGRES_USER,
        password=Config.POSTGRES_PASSWORD,
        host=Config.POSTGRES_HOST,
        port=Config.POSTGRES_PORT,
        db=Config.POSTGRES_DB,
    )

    add_section_to_logger(logger, "Acquiring and Saving Vector Data")
    vector_data_list = vector_data_acquisition(
        input_source="postgis",  # Read vector data from the specified source
        tables=Config.VECTOR_TABLES,
        engine=engine_postgis,
    )

    add_section_to_logger(logger, "Processing and Posting in API Vector Data")
    # Process vector data into PostGIS and post to STAC API
    try:
        geoprocessing_vector_data_postgis(
            engine=engine_postgis,
            gdf_list=vector_data_list,
        )
        report_data["vector_data"]["processed"] += len(Config.VECTOR_TABLES)
    except Exception as e:  # Catch any exception during vector data processing
        logger.error(f"Error during vector data processing: {e}")
        report_data["vector_data"]["errors"] += 1

    add_section_to_logger(logger, "Acquiring and Saving Raster Data")
    # Need to mounted the local file system to access raster data
    raster_data_list = list_local_raster_files(
        raster_path=Path(Config.RASTER_SOURCE_PATH)
    )  # List raster files from the specified path

    add_section_to_logger(logger, "Processing and Posting in API Raster Data")
    # Process raster data into PostGIS and post to STAC API
    try:
        geoprocessing_raster_data_postgis(
            engine=engine_postgis,
            rasters=raster_data_list,
            collection_id=Config.STAC_COLLECTION_ID,
            api_url=Config.STAC_API_URL,
        )
        report_data["raster_data"]["processed"] += len(raster_data_list)
    except Exception as e:  # Catch any exception during raster data processing
        logger.error(f"Error during raster data processing: {e}")
        report_data["raster_data"]["errors"] += 1

    generate_processing_report(report_data)


if __name__ == "__main__":
    main()
