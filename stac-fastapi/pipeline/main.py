import argparse
from pathlib import Path

from pipeline.config import Config
from pipeline.logging_setup import setup_logging
from pipeline.mapping import CSVDataRegistryForSourceCRS
from pipeline.modules.db.duckdb_utils import DuckDBManager
from pipeline.modules.io_tools.input_data import discover_geodata, read_csv_file
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
    parser.add_argument(
        "--csv-items",
        action="store_true",
        default=False,
        help="Flag to enable CSV data processing, including direct conversion of non-spatial CSVs to Parquet format.",
    )

    if return_parser:
        return parser
    return parser.parse_args()


def process_vector_pipeline(vector_files, args, report_data):
    """Process vector data.

    Args:
        vector_files (list of Path): List of vector file paths to process.
        args: Parsed command-line arguments.
        report_data (dict): Dictionary to store processing report data.
    """
    if len(vector_files) == 0:
        logger.info("No vector files found. Skipping vector data processing.")
        report_data["vector_data"]["skipped"] += 1

    else:
        try:
            # Handle CSV items separately
            if args.csv_items:
                csv_vector_files = [
                    vf for vf in vector_files if vf.suffix.lower() == ".csv"
                ]
                non_spatial_csvs = [
                    vf
                    for vf in csv_vector_files
                    if vf.stem.lower() not in CSVDataRegistryForSourceCRS.__members__
                ]

                if not csv_vector_files:
                    logger.warning(
                        "No CSV vector files found for --csv-items processing. Checking for non-spatial CSV."
                    )
                    report_data["vector_data"]["skipped"] += 1

                elif non_spatial_csvs:
                    with DuckDBManager() as duckdb_manager:
                        for vector_file in non_spatial_csvs:
                            df = read_csv_file(vector_file=vector_file)
                            duckdb_manager.save_df_to_parquet(
                                df=df,
                                output_file_name=vector_file.stem,
                            )
                    # Remove those saved to DuckDB from further processing
                    vector_files = [
                        vf for vf in vector_files if vf not in non_spatial_csvs
                    ]

                else:
                    logger.debug(
                        "All discovered CSVs are already in the CRS registry; nothing to save to DuckDB."
                    )

            # Convert vector files to GeoDataFrames
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


def process_raster_pipeline(raster_files, args, report_data):
    """Process raster data.

    Args:
        raster_files (list of Path): List of raster file paths to process.
        args: Parsed command-line arguments.
        report_data (dict): Dictionary to store processing report data.
    """
    if len(raster_files) == 0:
        logger.info("No raster files found. Skipping raster data processing.")
        report_data["raster_data"]["skipped"] += 1

    else:
        try:
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


def main():
    """Main function to run the geoprocessing pipeline.

    This function orchestrates the entire geoprocessing workflow, including:
    - Parsing command-line arguments
    - Setting up logging
    - Discovering geospatial data from the input path
    - Processing vector pipeline (from files -> GeoDataFrames -> PostGIS/DuckDB -> Vector API & STAC API)
    - Processing raster pipeline (from files -> COG -> PostGIS -> Raster API & STAC API)
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

    add_section_to_logger(logger, "Processing vector data pipeline")
    process_vector_pipeline(
        vector_files=vector_files,
        args=args,
        report_data=report_data,
    )

    add_section_to_logger(logger, "Processing raster data pipeline")
    process_raster_pipeline(
        raster_files=raster_files,
        args=args,
        report_data=report_data,
    )

    generate_processing_report(log=logger, report_data=report_data)


if __name__ == "__main__":
    main()
