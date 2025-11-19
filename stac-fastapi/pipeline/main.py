import argparse
from pathlib import Path

from pipeline.config import Config
from pipeline.logging_setup import setup_logging
from pipeline.modules.io_tools.input_data import discover_geodata
from pipeline.modules.processing.geoprocessing import (
    GeoprocessingVector,
    geoprocessing_raster_data,
    geoprocessing_vector_data,
)
from pipeline.utils import add_section_to_logger, generate_processing_report

logger = setup_logging()


class GeoprocessingPipelineError(Exception):
    """Custom exception for geoprocessing pipeline errors."""

    pass


def parse_args(return_parser=False):
    """Parse command-line arguments for the geoprocessing pipeline."""
    parser = argparse.ArgumentParser(description="Run the geoprocessing pipeline.")

    parser.add_argument(
        "--input",
        type=Path,
        default=Path(Config.INPUT_DATA_PATH),
        help="Path to the input source for data ingestion.",
    )
    parser.add_argument(
        "--crs",
        type=int,
        default=Config.GLOBAL_CRS,
        help="Global CRS to reproject all data to (EPSG code).",
    )
    parser.add_argument(
        "--stac-collection-id",
        type=str,
        default=Config.STAC_COLLECTION_ID,
        help="STAC Collection ID to associate with the ingested data.",
    )

    if return_parser:
        return parser
    return parser.parse_args()


def main():
    """Main function to run the geoprocessing pipeline.

    This function orchestrates the entire geoprocessing workflow, including:
    - Setting up logging
    - Connecting to the PostGIS database
    - Acquiring data from the input path
    - Processing vector data (from files -> GeoDataFrames -> PostGIS -> STAC API)
    - Processing raster data (from files -> COG -> PostGIS -> STAC API)
    - Generating a processing report
    """
    args = parse_args()

    add_section_to_logger(logger, "EOAPI Geoprocessing Pipeline")

    # Initialize report data structure
    report_data = {
        "vector_data": {"processed": 0, "errors": 0, "skipped": 0},
        "raster_data": {"processed": 0, "errors": 0, "skipped": 0},
    }

    add_section_to_logger(logger, "Discovering geospatial data in input path")
    geodata = discover_geodata(args.input)
    vector_files = geodata["vectors"]
    raster_files = geodata["rasters"]

    # Process vector data
    if len(vector_files) == 0:
        logger.info("No vector files found. Skipping vector data processing.")
        report_data["vector_data"]["skipped"] += 1
    else:
        try:
            add_section_to_logger(logger, "Geoprocessing vector data")
            vector_data_gdf_list = GeoprocessingVector.convert_vector_files_to_gdf(
                vector_files=vector_files
            )
            geoprocessing_vector_data(
                gdf_list=vector_data_gdf_list,
                target_crs=args.crs,
                stac_collection_id=args.stac_collection_id,
                stac_api_url=Config.STAC_API_URL,
            )
            report_data["vector_data"]["processed"] += len(vector_data_gdf_list)
        except GeoprocessingPipelineError as e:
            logger.error(f"Error during vector data processing: {e}")
            report_data["vector_data"]["errors"] += 1

    # Process raster data
    if len(raster_files) == 0:
        logger.info("No raster files found. Skipping raster data processing.")
        report_data["raster_data"]["skipped"] += 1
    else:
        try:
            add_section_to_logger(logger, "Geoprocessing raster data")
            geoprocessing_raster_data(
                rasters=raster_files,
                target_crs=args.crs,
                stac_collection_id=args.stac_collection_id,
                api_url=Config.STAC_API_URL,
            )
            report_data["raster_data"]["processed"] += len(raster_files)
        except GeoprocessingPipelineError as e:
            logger.error(f"Error during raster data processing: {e}")
            report_data["raster_data"]["errors"] += 1

    generate_processing_report(log=logger, report_data=report_data)


if __name__ == "__main__":
    main()
