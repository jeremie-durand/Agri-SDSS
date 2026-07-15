import argparse
from pathlib import Path

import structlog
from gis_pipeline.core.config import Config
from gis_pipeline.core.exceptions import RasterProcessingError

logger = structlog.get_logger()


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
        "--collection",
        type=str,
        default=Config.STAC_COLLECTION_ID,
        help="Collection ID to associate with the ingested data.",
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
    import fiona
    import geopandas as gpd
    from gis_pipeline.modules.db.duckdb_utils import DuckDBManager
    from gis_pipeline.modules.db.pg_utils import PostGISManager
    from gis_pipeline.modules.io_tools.input_data import (
        detect_non_spatial_csv,
        extract_gpkg_fk_schema,
        read_csv_file,
    )
    from gis_pipeline.modules.processing.geoprocessing import (
        GeoprocessingVector,
        geoprocessing_vector_data,
        stamp_gee_flags_on_field_boundaries,
    )
    from gis_pipeline.services.mapping import CHUNK_SIZE, QGISInternalLayers

    if len(vector_files) == 0:
        logger.info("No vector files found. Skipping vector data processing.")
        report_data["vector_data"]["skipped"] += 1
        return

    # Non-spatial CSVs → DuckDB only
    try:
        csv_files = [vf for vf in vector_files if vf.suffix.lower() == ".csv"]
        non_spatial_csv_files = detect_non_spatial_csv(csv_files=csv_files) or []
        report_data["vector_data"]["non_spatial_csv"] += len(non_spatial_csv_files)

        if non_spatial_csv_files:
            with DuckDBManager() as duckdb_manager:
                for non_spatial_csv_file in non_spatial_csv_files:
                    df = read_csv_file(vector_file=non_spatial_csv_file)
                    duckdb_manager.save_df_to_parquet(
                        df=df,
                        output_file_name=non_spatial_csv_file.stem,
                    )
    except Exception as e:
        logger.error(f"Error during non-spatial CSV processing: {e}")
        report_data["vector_data"]["errors"] += 1

    # Spatial files: one file → one layer → one chunk at a time to bound peak RAM
    internal_layer_names = {e.value for e in QGISInternalLayers}
    spatial_files = [vf for vf in vector_files if vf not in non_spatial_csv_files]

    for vector_file in spatial_files:
        # Spatial CSVs: load in one shot (they are small by nature)
        if vector_file.suffix.lower() == ".csv":
            try:
                gdf_list = GeoprocessingVector.convert_vector_files_to_gdf(
                    [vector_file]
                )
                if gdf_list:
                    geoprocessing_vector_data(
                        gdf_list=gdf_list,
                        target_crs=args.crs,
                        collection_id=args.collection,
                    )
                    report_data["vector_data"]["processed"] += len(gdf_list)
            except Exception as e:
                logger.error(f"Error processing {vector_file.name}: {e}")
                report_data["vector_data"]["errors"] += 1
            continue

        # Other vector formats: iterate layers without holding them all in memory
        try:
            all_layers = fiona.listlayers(vector_file)
        except Exception as e:
            logger.warning(f"Could not list layers in {vector_file.name}: {e}")
            report_data["vector_data"]["errors"] += 1
            continue

        valid_layers = [
            layer for layer in all_layers if layer.lower() not in internal_layer_names
        ]

        # Accumulate {sqlite_layer → pg_table} for FK extraction after all layers load
        fk_layer_name_map: dict[str, str] = {}

        for layer in valid_layers:
            try:
                with fiona.open(vector_file, layer=layer) as src:
                    total_rows = len(src)

                if total_rows == 0:
                    logger.info(f"Skipping empty layer '{layer}' in {vector_file.name}")
                    continue

                raw_name = (
                    f"{vector_file.stem}_{layer.strip()}"
                    if len(valid_layers) > 1
                    else vector_file.stem
                )
                clean_name = GeoprocessingVector._harmonize_name_gdf(name=raw_name)
                is_chunked = total_rows > CHUNK_SIZE

                for chunk_idx, start in enumerate(range(0, total_rows, CHUNK_SIZE)):
                    gdf_chunk = gpd.read_file(
                        vector_file, layer=layer, rows=slice(start, start + CHUNK_SIZE)
                    )

                    geoprocessing_vector_data(
                        gdf_list=[(clean_name, gdf_chunk)],
                        target_crs=args.crs,
                        collection_id=args.collection,
                        override_method="replace" if chunk_idx == 0 else "append",
                        write_parquet=not is_chunked,
                        gid_offset=start,
                    )

                if vector_file.suffix.lower() == ".gpkg":
                    fk_layer_name_map[layer] = clean_name

                report_data["vector_data"]["processed"] += 1
            except Exception as e:
                logger.error(
                    f"Error processing layer '{layer}' in {vector_file.name}: {e}"
                )
                report_data["vector_data"]["errors"] += 1
                continue

        # Apply FK constraints for .gpkg files after all layers are loaded
        if vector_file.suffix.lower() == ".gpkg" and fk_layer_name_map:
            try:
                fk_defs = extract_gpkg_fk_schema(vector_file, fk_layer_name_map)
                if fk_defs:
                    with PostGISManager() as pg_manager:
                        pg_manager.apply_foreign_keys(fk_defs)
                    logger.info(
                        f"Applied {len(fk_defs)} FK constraint(s) for {vector_file.name}"
                    )
            except Exception as e:
                logger.warning(
                    f"Could not apply FK constraints for {vector_file.name}: {e}"
                )

    # Stamp GEE flags on field boundaries, needs to run after all vector layers are ingested to ensure it can find the relevant field boundary layers
    stamp_gee_flags_on_field_boundaries()


def process_raster_pipeline(raster_files, args, report_data):
    """Process raster data.

    Args:
        raster_files (list of Path): List of raster file paths to process.
        args: Parsed command-line arguments.
        report_data (dict): Dictionary to store processing report data.
    """
    from gis_pipeline.modules.processing.geoprocessing import geoprocessing_raster_data

    if len(raster_files) == 0:
        logger.info("No raster files found. Skipping raster data processing.")
        report_data["raster_data"]["skipped"] += 1

    else:
        try:
            geoprocessing_raster_data(
                rasters=raster_files,
                target_crs=args.crs,
                stac_collection_id=args.collection,
                api_url=Config.STAC_API_URL,
            )
            report_data["raster_data"]["processed"] += len(raster_files)
        except RasterProcessingError as e:
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
    import uuid

    import structlog
    from gis_pipeline.core.logging_setup import setup_logging
    from gis_pipeline.modules.io_tools.input_data import discover_geodata
    from gis_pipeline.utils import add_section_to_logger, generate_processing_report

    setup_logging()
    structlog.contextvars.bind_contextvars(run_id=str(uuid.uuid4())[:8])

    global logger
    logger = structlog.get_logger()

    args = parse_args()

    add_section_to_logger(logger, "EOAPI Geoprocessing Pipeline")

    # Initialize report data structure
    report_data = {
        "vector_data": {
            "processed": 0,
            "errors": 0,
            "skipped": 0,
            "non_spatial_csv": 0,
        },
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
