# eoapi-template/demo/geoprocessing.py
import logging

logger = logging.getLogger(__name__)

import json
import shutil
import subprocess
import time
from pathlib import Path

import geopandas as gpd
import pandas as pd
import rasterio
import sqlalchemy
from demo.config import Config
from demo.init_postgis import (
    ensure_columns_exist,
    insert_gdf_to_postgis,
    set_dummy_date_for_table,
)
from demo.mapping import attribute_null_mapping, vector_stac_columns
from demo.processing_stac import (
    StacApiClient,
    build_stac_items_from_table,
    create_stac_item_from_raster,
    validate_stac,
)
from demo.util import add_process_to_logger
from pydantic import ValidationError
from rasterio.errors import CRSError, RasterioError
from rasterio.warp import Resampling, calculate_default_transform, reproject
from sqlalchemy import text


class GeoprocessingVector:
    def __init__(self, config: Config, gdf: gpd.GeoDataFrame):
        self.config = config
        self.gdf = gdf

    def validate_vector_data(self):
        """Validate the input GeoDataFrame for vector data processing."""
        logger.info("Validating input GeoDataFrame for vector data processing...")
        if not isinstance(self.gdf, gpd.GeoDataFrame):
            raise ValueError(
                "Input must be a valid GeoDataFrame with a geometry column."
            )
        if self.gdf.geometry.name not in self.gdf.columns:
            raise ValueError(
                "Input must be a valid GeoDataFrame with a geometry column."
            )
        if self.gdf.empty:
            raise ValueError("GeoDataFrame is empty.")

        if any(
            [
                not isinstance(self.gdf, gpd.GeoDataFrame),
                not self.gdf.crs,
                self.gdf.crs.to_epsg() is None,
            ]
        ):
            raise ValueError("GeoDataFrame must have a CRS set before harmonizing.")

        # Reset index to avoid issues with GeoDataFrame
        self.gdf = self.gdf.reset_index(drop=True)

    def harmonize_gdf(
        self,
        columns_mapping: dict = None,
        expected_types: dict = None,
        drop_duplicates: bool = True,
        drop_null_geoms: bool = True,
        rename_columns: bool = True,
    ) -> gpd.GeoDataFrame:
        """Harmonise a GeoDataFrame using different methods.

        Args:
            columns_mapping: Optional mapping of column names to rename.
            expected_types: Optional mapping of column names to expected types.
            drop_duplicates: Whether to drop duplicate rows. Default is True.
            drop_null_geoms: Whether to drop rows with null geometries. Default is True.
            rename_columns: Whether to rename columns to a standard format. Default is True.

        Notes:
            This function performs several harmonization steps:
            - Renaming columns based on a mapping
            - Removing duplicates
            - Dropping rows with null geometries
            - Handling null values in attributes
            - Casting columns to expected types if provided
        """
        if any(
            [
                not isinstance(self.gdf, gpd.GeoDataFrame),
                self.gdf.geometry.name not in self.gdf.columns,
            ]
        ):
            raise ValueError(
                "Input must be a valid GeoDataFrame with a geometry column."
            )

        # Remove duplicate rows
        if drop_duplicates:
            self.gdf = self.gdf.drop_duplicates()

        # Drop null geometries and copy BEFORE any assignment to columns
        if drop_null_geoms and self.gdf.geometry.isnull().any():
            self.gdf = self.gdf[~self.gdf.geometry.isnull()].copy()

        # Replace spaces in column names with underscores
        if rename_columns:
            self.gdf.columns = self.gdf.columns.str.replace(" ", "_", regex=False)
            self.gdf.columns = self.gdf.columns.str.replace("-", "_", regex=False)
            # gdf.columns = gdf.columns.str.lower()

        # Handle null values in attributes
        null_like = list(attribute_null_mapping.keys())
        for col in self.gdf.columns:
            if self.gdf[col].dtype == "object":
                self.gdf[col] = self.gdf[col].replace(null_like, None)
                self.gdf[col] = self.gdf[col].where(pd.notnull(self.gdf[col]), None)

        # Cast columns to expected types if provided
        if expected_types:
            for col, typ in expected_types.items():
                if col in self.gdf.columns:
                    self.gdf[col] = self.gdf[col].astype(typ)

        # Rename columns based on the mapping if provided
        if columns_mapping:
            self.gdf = self.gdf.rename(columns=columns_mapping)

    def clean_geometries_gdf(
        self,
        is_fix_invalid: bool = True,
        is_check_overlaps: bool = False,
        geometry_column: str = None,
    ) -> gpd.GeoDataFrame:
        """Clean geometries in a GeoDataFrame.

        Args:
            fix_invalid: Whether to fix invalid geometries.
            check_overlaps: Whether to check for overlapping polygons.
            geometry_column: Name of the geometry column in the GeoDataFrame.


        Notes:
            This function performs the following cleaning steps:
            - Fixing invalid geometries
            - Removing geometries that are still invalid after fixing
            - Checking for overlaps in polygons if applicable
        """
        logger.info("Starting geometry cleaning process...")

        if not isinstance(self.gdf, gpd.GeoDataFrame):
            raise ValueError(
                "Input must be a valid GeoDataFrame with a geometry column."
            )

        # Auto-detect geometry column if not provided
        logger.info("Detecting geometry column...")
        if geometry_column is None:
            for col in ["geometry", "geom"]:
                if col in self.gdf.columns:
                    geometry_column = col
                    break
            else:
                logger.error(
                    "No geometry column ('geometry' or 'geom') found in the GeoDataFrame."
                )
                raise ValueError(
                    "GeoDataFrame must contain a geometry column named 'geometry' or 'geom'."
                )

        # Fix invalid geometries if requested
        if is_fix_invalid:
            logger.info(f"Fixing invalid geometries...")
            if geometry_column not in self.gdf.columns:
                logger.error(
                    f"Geometry column '{geometry_column}' not found in the GeoDataFrame."
                )
                raise ValueError(
                    f"GeoDataFrame must contain a geometry column named '{geometry_column}'."
                )

        # Remove geometries that are still invalid after fixing and listed them in a warning
        if self.gdf[geometry_column].isnull().any():
            logger.warning(
                "Some geometries are still invalid after fixing. Removing them from the GeoDataFrame."
            )
            logger.warning(
                f"Removing {self.gdf[geometry_column].isnull().sum()} rows with null geometries."
            )
            self.gdf = self.gdf[self.gdf[geometry_column].notnull()]

        if is_check_overlaps:
            logger.info("Checking for overlapping polygons...")
            overlaps = self.find_overlapping_polygons(geometry_column)
            if overlaps:
                logger.warning(f"Overlapping polygons detected: {overlaps}")

        # Harmonize geometry column name to 'geom' for downstream compatibility
        if geometry_column != "geom":
            self.gdf = self.gdf.rename(columns={geometry_column: "geom"})
            self.gdf.set_geometry("geom", inplace=True)

        # Other error cases for geometries can be added here, such as self-intersections, etc.

    def harmonize_crs_gdf(
        self, target_crs: str | int = "EPSG:4326"
    ) -> gpd.GeoDataFrame:
        """Harmonise the CRS (Coordinate Reference System) of a GeoDataFrame.

        Args:
            target_crs: Target CRS as an EPSG code (e.g., 4326).

        """
        logger.info("Starting CRS harmonization process...")
        if not isinstance(self.gdf, gpd.GeoDataFrame):
            raise ValueError("Input must be a GeoDataFrame.")

        # Ensure the geometry column is set to the correct CRS
        if not self.gdf.crs:
            raise ValueError("GeoDataFrame must have a CRS set before harmonizing.")

        # Reproject the GeoDataFrame to the target CRS if it is different
        if (
            self.gdf.crs.to_string() != str(target_crs)
            and self.gdf.crs.to_epsg() != target_crs
        ):
            self.gdf = self.gdf.to_crs(target_crs)

    def find_overlapping_polygons(self, geometry_column: str) -> list[tuple[int, int]]:
        """Find overlapping polygons in a GeoDataFrame.

        Args:
            geometry_column: The name of the geometry column in the GeoDataFrame.

        Returns:
            A list of tuples, each containing the indices of overlapping polygons.
        """
        poly_gdf = self.gdf[self.gdf.geom_type.isin(["Polygon", "MultiPolygon"])]
        if poly_gdf.empty:
            return []

        sindex = poly_gdf.sindex
        overlaps = []
        for idx, geom in poly_gdf[geometry_column].items():
            possible_matches_index = list(sindex.intersection(geom.bounds))
            possible_matches_index = [i for i in possible_matches_index if i != idx]
            for other_idx in possible_matches_index:
                other_geom = poly_gdf.at[other_idx, geometry_column]
                if geom.intersects(other_geom):
                    overlaps.append((idx, other_idx))
        return overlaps


def geoprocessing_vector_data_postgis(
    engine: sqlalchemy.engine.Engine, gdf_list: list[tuple[str, gpd.GeoDataFrame]]
):
    """Process vector data and insert into PostGIS and STAC API.

    Args:
        engine: SQLAlchemy engine connected to the database.
        gdf_list: List of tuples containing table names and GeoDataFrames to process.

    Notes:
        This function performs the following steps:
        - Validates the input GeoDataFrame
        - Harmonizes the GeoDataFrame (renaming columns, removing duplicates, etc.)
        - Cleans geometries (fixing invalid geometries, checking overlaps)
        - Harmonizes CRS (Coordinate Reference System)
        - Inserts processed vector data into PostGIS
        - Prepares the table for STAC processing
        - Builds and validates STAC items from the table
        - Creates and validates a STAC collection
        - Posts the collection and items to the STAC API
        - Logs the processing steps and any errors encountered
    """
    add_process_to_logger(logger, "Processing Vector Data PostGIS")
    logger.info(f"Found {len(gdf_list)} vector tables to process.")
    # Iterate over each table and its corresponding GeoDataFrame
    for table, gdf in gdf_list:
        logger.info(f"Processing vector data for table: {table}")

        # Create an instance of GeoprocessingVector
        processor = GeoprocessingVector(config=Config, gdf=gdf)
        processor.validate_vector_data()
        processor.harmonize_gdf()
        processor.clean_geometries_gdf()
        processor.harmonize_crs_gdf()

        # Get the processed GeoDataFrame
        final_gdf = processor.gdf
        logger.info(f"Vector data for table {table} processed successfully.")

        # Generate data before inserting into PostGIS if needed
        # Here will be function to generate data before inserting into PostGIS if needed

        # Insert processed vector data into PostGIS
        insert_gdf_to_postgis(
            engine=engine,
            gdf=final_gdf,
            table_name=table,
        )
        logger.info(f"GeoDataFrame inserted into PostGIS table '{table}' successfully.")

        logger.info(f"Preparing PostGIS table '{table}' for STAC processing...")
        # Ensure the table has the required STAC columns
        ensure_columns_exist(
            engine=engine, table_name=table, columns=vector_stac_columns
        )
        # Set dummy dates for start_date and end_date in the table
        set_dummy_date_for_table(engine=engine, table=table)
        # Check table columns
        with engine.connect() as conn:
            result = conn.execute(sqlalchemy.text(f'SELECT * FROM "{table}" LIMIT 10;'))
            table_heads = result.keys()
            logger.info(f"Table '{table}' columns: {table_heads}")

        # Build and validate STAC items from the table
        items = build_stac_items_from_table(engine=engine, table=table)
        for item in items:
            if hasattr(item, "to_dict"):
                validate_stac(stac_obj=item.to_dict(), stac_type="item")
            else:
                validate_stac(stac_obj=item, stac_type="item")

        # Create a STAC API client
        stac_client = StacApiClient(api_url=Config.STAC_API_URL)

        # Create and validate STAC collection
        collection_id_table = f"{Config.STAC_COLLECTION_ID}_{table}"  # Unique collection ID for each table
        collection = stac_client.create_and_validate_collection(
            items=items, collection_id=collection_id_table
        )

        # Post collection to STAC API, one collection per table
        stac_client.post_collection(collection)

        # Post items to STAC API
        stac_client.post_items(items=items, collection_id=collection_id_table)

        logger.info(f"Vector data for table {table} processed and posted to STAC API.")

    logger.info("Vector data processing completed successfully.")


class GeoprocessingRaster:
    def __init__(self, config: Config, raster_paths: list[Path] | Path):
        self.config = config
        # Ensure raster_paths is a list of Path objects
        if isinstance(raster_paths, Path):
            raster_paths = [raster_paths]
        self.raster_paths = [
            Path(p) if not isinstance(p, Path) else p for p in raster_paths
        ]

    @staticmethod
    def validate_raster_data(raster_paths: list[Path] | Path):
        """Validate input raster files for processing."""
        logger.info("Validating input raster files for processing...")

        if raster_paths is None:
            raise ValueError("No raster files provided.")

        if isinstance(raster_paths, Path):
            raster_paths = [raster_paths]

        # Ensure GDAL commands are available
        for cmd in ("gdalwarp", "gdaladdo"):
            if shutil.which(cmd) is None:
                raise RuntimeError(f"GDAL command '{cmd}' not found.")

        for raster_path in raster_paths:
            logger.debug(f"Validating raster: {raster_path}")

            # Check that raster_path is a Path object and exists
            if not isinstance(raster_path, Path):
                raise ValueError(
                    f"Raster path must be a pathlib.Path object, got {type(raster_path)}"
                )
            if not raster_path.exists():
                raise FileNotFoundError(f"Raster file does not exist: {raster_path}")

            # Check file extension
            if raster_path.suffix.lower() not in [".tif", ".tiff"]:
                raise ValueError(f"Invalid raster format for: {raster_path}")

            try:
                with rasterio.open(raster_path) as src:
                    # CRS check
                    if src.crs is None or not src.crs.is_valid:
                        raise ValueError(
                            f"Raster has an invalid or missing CRS: {raster_path}"
                        )

                    # Dimension checks
                    if src.width <= 0 or src.height <= 0:
                        raise ValueError(
                            f"Raster has invalid dimensions (width/height): {raster_path}"
                        )

                    # Band count check
                    if src.count <= 0:
                        raise ValueError(
                            f"Raster has invalid band count: {raster_path}"
                        )

                    # Transform check
                    if not src.transform:
                        raise ValueError(
                            f"Raster has no valid transform: {raster_path}"
                        )

            except (RasterioError, CRSError) as e:
                raise ValueError(f"Cannot open raster {raster_path}: {e}")

        logger.info(f"All {len(raster_paths)} raster file(s) passed validation.")

    def harmonize_raster_data(
        self,
        input_rasters: list[Path] | Path,
        output_dir: Path,
        reference_crs: int = Config.GLOBAL_CRS,
        reference_nodata_value: float = None,
    ):
        """Harmonize rasters and save to output directory.

        Args:
            input_rasters: List of input raster files to harmonize or a single raster file.
            output_dir: Directory where the harmonized raster will be saved.
            reference_crs: Target CRS to harmonize to. Default is project CRS.
            reference_nodata_value: NoData value to set in the output raster.
        """
        if output_dir is None or not isinstance(output_dir, Path):
            raise ValueError("Invalid output directory.")
        if not input_rasters or len(input_rasters) == 0:
            raise ValueError(
                "input_rasters must be a non-empty list of pathlib.Path objects"
            )

        output_dir.mkdir(parents=True, exist_ok=True)

        if not isinstance(input_rasters, list):
            input_rasters = [input_rasters]

        # Ensure input_rasters is a list of Path objects
        assert all(
            isinstance(p, Path) for p in input_rasters
        ), "All input_rasters must be pathlib.Path objects"

        try:
            for input_raster in input_rasters:
                self._harmonize_single_raster(
                    input_raster=input_raster,
                    output_dir=output_dir,
                    reference_crs=reference_crs,
                    reference_nodata_value=reference_nodata_value,
                )
        except CRSError as e:
            raise RuntimeError(f"Invalid CRS code: {reference_crs}") from e
        except RasterioError as e:
            raise RuntimeError(f"Transformation failed for CRS: {reference_crs}") from e

    def _harmonize_single_raster(
        self,
        input_raster: Path,
        output_dir: Path,
        reference_crs: int,
        reference_nodata_value: float,
    ) -> None:
        """Harmonize a single raster file and save to output directory.

        Args:
            input_raster: Path to the input raster file.
            output_dir: Directory where the harmonized raster will be saved.
            reference_crs: Target CRS to harmonize to.
            reference_nodata_value: NoData value to set in the output raster.

        Notes:
            Each output file will be named <original_stem>_harmonized.tif.
            Here are the harmonization steps:
                1. Check if the input raster exists and is a valid raster file.
                2. Create a new raster file with the same metadata as the input.
                3. Reproject the raster to the target CRS if it differs from the input CRS.
                4. Write the reprojected raster to the output file.
        """
        logger.info(f"Harmonizing raster file: {input_raster}")
        if not input_raster.exists():
            raise FileNotFoundError(f"Input raster file {input_raster} does not exist.")
        if input_raster.suffix.lower() not in (".tif", ".tiff"):
            raise ValueError(f"Unsupported raster format: {input_raster.suffix}")

        output_path = (
            output_dir / f"{input_raster.stem}_harmonized{input_raster.suffix}"
        )
        if output_path.exists():
            output_path.unlink()

        with rasterio.open(input_raster) as src:
            dst_profile = src.profile.copy()
            if reference_nodata_value is not None:
                dst_profile.update(nodata=reference_nodata_value)

            dst_profile.update(
                {
                    "driver": "GTiff",
                    "tiled": True,
                    "blockxsize": 256,
                    "blockysize": 256,
                    "compress": "deflate",
                    "bigtiff": "yes",
                }
            )

            if src.crs != reference_crs:
                transform, width, height = calculate_default_transform(
                    src.crs, reference_crs, src.width, src.height, *src.bounds
                )
                dst_profile.update(
                    {
                        "crs": reference_crs,
                        "transform": transform,
                        "width": width,
                        "height": height,
                    }
                )
                with rasterio.open(output_path, "w", **dst_profile) as dst:
                    for i in range(1, src.count + 1):
                        reproject(
                            source=rasterio.band(src, i),
                            destination=rasterio.band(dst, i),
                            src_transform=src.transform,
                            src_crs=src.crs,
                            dst_transform=transform,
                            dst_crs=reference_crs,
                            resampling=Resampling.nearest,
                        )
            else:
                with rasterio.open(output_path, "w", **dst_profile) as dst:
                    for i in range(1, src.count + 1):
                        dst.write(src.read(i), i)
        logger.info(f"Raster harmonized and saved to: {output_path}")

    @staticmethod
    def build_cog_wrap_cmd(
        input_raster: Path,
        output_cog: Path,
        reference_crs: int = Config.GLOBAL_CRS,
        compress: str = "DEFLATE",
    ) -> list[str]:
        """Build the command to convert a raster file to a COG (Cloud Optimized GeoTIFF).

        Args:
            input_raster: Path to the input raster file.
            output_cog: Path where the COG will be saved.
            reference_crs: EPSG code for reprojection. Default is project CRS.

        Returns:
            List of command arguments for subprocess.run.
        """
        return [
            "gdalwarp",
            "-t_srs",
            f"EPSG:{reference_crs}",
            "-of",
            "COG",
            "-dstalpha",
            "-co",
            f"COMPRESS={compress}",
            str(
                input_raster
            ),  # String conversion from Path to ensure compatibility with subprocess
            str(
                output_cog
            ),  # String conversion from Path to ensure compatibility with subprocess
        ]

    @staticmethod
    def process_raster_to_cog(
        input_raster: Path,
        output_cog: Path,
        reference_crs: int = Config.GLOBAL_CRS,
        compress: str = "DEFLATE",
    ) -> None:
        """Convert a raster file to create a COG (Cloud Optimized GeoTIFF).

        Args:
            input_raster: Path to the input raster file.
            output_path: Path where the COG will be saved.
            reference_crs: EPSG code for reprojection. Default is project CRS.
        """
        if not input_raster or not Path(input_raster).exists():
            raise FileNotFoundError(f"Invalid input raster: {input_raster}")

        # Ensure output directory exists
        output_cog.parent.mkdir(parents=True, exist_ok=True)

        # Build GDAL command to create COG
        warp_cmd = GeoprocessingRaster.build_cog_wrap_cmd(
            input_raster=input_raster,
            output_cog=output_cog,
            reference_crs=reference_crs,
            compress=compress,
        )

        logger.info(f"Running gdalwarp command: {' '.join(warp_cmd)}")
        try:
            # Run gdalwarp to create the COG
            warp_result = subprocess.run(
                warp_cmd, check=True, capture_output=True, text=True
            )
        except subprocess.CalledProcessError as e:
            logger.error(
                f"gdalwarp failed for {input_raster} -> {output_cog}: {(e.stderr or '').strip()}"
            )
            raise RuntimeError(
                f"gdalwarp failed for {input_raster} -> {output_cog} "
                f"(exit code {e.returncode}). See logs above for details."
            )
        # Always log stdout/stderr, even on failure
        logger.debug(f"gdalwarp STDOUT:\n{warp_result.stdout.strip()}")
        logger.debug(f"gdalwarp STDERR:\n{warp_result.stderr.strip()}")

        # Validate the created COG
        try:
            GeoprocessingRaster.validate_raster_data(output_cog)
        except ValidationError as e:
            logger.error(f"Validation failed for {output_cog}: {e}")
            raise

    @staticmethod
    def extract_cog_metadata(cog_file: Path) -> dict:
        """Extract metadata from a COG file.

        Args:
            cog_file: Path to the COG file.

        Returns:
            Dictionary containing metadata such as id, datetime, bbox, geometry, and COG URL.
        """
        if not cog_file.exists():
            raise FileNotFoundError(f"COG file {cog_file} does not exist.")
        if cog_file is None or not isinstance(cog_file, (str, Path)):
            raise ValueError("Invalid input raster: None or incorrect type")
        if not Path(cog_file).exists():
            raise FileNotFoundError(f"Invalid input raster: {cog_file}")

        with rasterio.open(cog_file) as src:
            if not src.tags():
                raise ValueError("COG file has no metadata.")

            bounds = src.bounds
            geometry = {
                "type": "Polygon",
                "coordinates": [
                    [
                        [bounds.left, bounds.bottom],
                        [bounds.right, bounds.bottom],
                        [bounds.right, bounds.top],
                        [bounds.left, bounds.top],
                        [bounds.left, bounds.bottom],
                    ]
                ],
            }
            dt = src.tags().get("TIFFTAG_DATETIME", "2024-01-01T00:00:00Z")

            return {
                "id": cog_file.stem,
                "datetime": dt,
                "bbox": list(bounds),
                "geometry": geometry,
            }

    @staticmethod
    def insert_raster_metadata_to_postgis(
        engine: sqlalchemy.engine.Engine, metadata: dict, table_name: str
    ) -> None:
        """Insert metadata into a PostGIS table.

        Args:
            engine: SQLAlchemy engine connected to the PostGIS database.
            metadata: Dictionary containing metadata to insert.
            table_name: Name of the PostGIS table to insert data into.
        """
        if metadata is None or not isinstance(metadata, dict):
            raise ValueError("Metadata must be a non-empty dictionary.")
        if not table_name or not isinstance(table_name, str):
            raise ValueError("Table name must be a non-empty string.")

        geometry_json = json.dumps(metadata["geometry"])
        bbox_list = list(metadata["bbox"])

        sql = text(
            f"""
            INSERT INTO {table_name} (id, datetime, bbox, geometry)
            VALUES (:id, :datetime, :bbox, ST_SetSRID(ST_GeomFromGeoJSON(:geometry), 4326))
            ON CONFLICT (id) DO UPDATE SET
                datetime = EXCLUDED.datetime,
                bbox = EXCLUDED.bbox,
                geometry = EXCLUDED.geometry
        """
        )

        try:
            with engine.begin() as conn:  # begin = auto-commit on exit
                conn.execute(
                    sql,
                    {
                        "id": metadata["id"],
                        "datetime": metadata["datetime"],
                        "bbox": bbox_list,
                        "geometry": geometry_json,
                    },
                )
        except Exception as e:
            logger.error(f"Error inserting metadata into PostGIS: {e}")
            raise RuntimeError("Critical error while inserting metadata into PostGIS.")


def geoprocessing_raster_data_postgis(
    engine: sqlalchemy.engine.Engine,
    rasters: list[Path],
    collection_id: str,
    api_url: str,
):
    """Process raster data by harmonizing, creating COGs, extracting metadata, saving in postgis and posting to STAC API.

    Args:
        engine: SQLAlchemy engine connected to the PostGIS database.
        rasters: List of raster file names to process.
        collection_id: Unique identifier for the STAC collection.
        api_url: URL of the STAC API to post the collection and items.

    Notes:
        Here are the steps performed:
        1. Harmonize raster data to ensure consistent CRS and NoData values.
        2. Process each raster to create a COG (Cloud Optimized GeoTIFF).
        3. Extract metadata from the COG files.
        4. Insert metadata into PostGIS.
        5. Create STAC items from the COG files.
        6. Validate STAC items.
        7. Create and validate a STAC collection.
        8. Post the collection to the STAC API.
        9. Post the items to the STAC API.
    """
    add_process_to_logger(logger, "Processing Raster Data PostGIS")

    if not rasters:
        raise RuntimeError("No raster files found in the specified directory.")

    processing = GeoprocessingRaster(config=Config, raster_paths=rasters)

    # Validate raster data
    try:
        processing.validate_raster_data(raster_paths=rasters)
    except ValueError as e:
        logger.error(f"Raster validation failed: {e}")
        raise RuntimeError(
            "Critical error during raster validation. Check logs for details."
        )

    # Harmonize raster data
    logger.info(f"Found {len(rasters)} raster files to process.")
    processing.harmonize_raster_data(
        input_rasters=rasters,
        output_dir=Path(Config.RASTER_HARMONIZED_PATH),
        reference_crs=Config.GLOBAL_CRS,
        reference_nodata_value=None,
    )

    # List harmonized raster files
    harmonized_dir = Path(Config.RASTER_HARMONIZED_PATH)
    harmonized_rasters = [
        f
        for f in harmonized_dir.iterdir()
        if f.suffix.lower() in (".tif", ".tiff")
        and f.name.endswith("_harmonized" + f.suffix)
    ]
    cog_dir = Path(Config.RASTER_COG_PATH)
    cog_dir.mkdir(parents=True, exist_ok=True)
    item_raster_list = []

    for harmonized_file in harmonized_rasters:
        logger.info(f"Processing harmonized raster file: {harmonized_file}")
        stem = harmonized_file.stem.replace("_cog", "")
        cog_file = cog_dir / f"{stem}_cog{harmonized_file.suffix}"

        # Backup if COG exists
        backup_file = None
        if cog_file.exists():
            timestamp = int(time.time())
            backup_file = cog_file.with_name(
                f"{cog_file.stem}_old_{timestamp}{cog_file.suffix}"
            )
            cog_file.rename(backup_file)
            logger.info(f"Existing COG moved to backup: {backup_file}")

        try:
            # Process to COG (static method)
            GeoprocessingRaster.process_raster_to_cog(
                input_raster=harmonized_file,
                output_cog=cog_file,
                reference_crs=Config.GLOBAL_CRS,
            )

            # Extract metadata (static method)
            metadata = GeoprocessingRaster.extract_cog_metadata(cog_file)
            logger.info(f"Extracted metadata: {metadata}")

            # Insert into PostGIS (static method)
            GeoprocessingRaster.insert_raster_metadata_to_postgis(
                engine=engine, metadata=metadata, table_name="cogs"
            )

            # Create STAC item
            item = create_stac_item_from_raster(
                raster_path=cog_file, item_id=cog_file.stem
            )
            validate_stac(item.to_dict(), stac_type="item")
            item_raster_list.append(item)

            # Remove backup if all good
            if backup_file and backup_file.exists():
                backup_file.unlink()

        except Exception as e:
            logger.error(f"Error during processing of {cog_file}: {e}")
            if backup_file and backup_file.exists():
                if cog_file.exists():
                    cog_file.unlink()
                backup_file.rename(cog_file)
            continue

    # Create a STAC API client
    stac_client = StacApiClient(api_url=api_url)

    # Create and validate STAC collection
    collection_id_raster = f"{collection_id}_raster"
    collection = stac_client.create_and_validate_collection(
        items=item_raster_list, collection_id=collection_id_raster
    )

    # Post collection to STAC API
    stac_client.post_collection(collection)

    # Post items to STAC API
    stac_client.post_items(items=item_raster_list, collection_id=collection_id_raster)
