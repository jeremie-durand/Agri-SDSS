import hashlib
import re
import subprocess
import time
from pathlib import Path

import fiona
import geopandas as gpd
import pandas as pd
import rasterio
from gis_pipeline.core.config import Config
from gis_pipeline.core.logging_setup import handle_error, setup_logging
from gis_pipeline.modules.db.duckdb_utils import DuckDBManager
from gis_pipeline.modules.db.pg_utils import PostGISManager
from gis_pipeline.modules.io_tools.input_data import read_csv_file
from gis_pipeline.modules.processing.processing_stac import (
    StacApiClient,
    build_stac_collection_from_items,
    build_stac_items_from_cog,
)
from gis_pipeline.services.mapping import (
    AttributeNullValues,
    ColumnMappings,
    CSVDataRegistryForSourceCRS,
    NamingPatterns,
)
from gis_pipeline.utils import add_process_to_logger

logger = setup_logging()


class GeoprocessingVector:
    def __init__(
        self,
        gdf: gpd.GeoDataFrame,
        target_crs: str,
        collection_id: str,
    ):
        self.gdf = gdf
        self.target_crs = target_crs
        self.collection_id = collection_id

    def _find_overlapping_polygons(self, geometry_column: str) -> list[tuple[int, int]]:
        """Find overlapping polygons in a GeoDataFrame.

        Args:
            geometry_column: The name of the geometry column in the GeoDataFrame.

        Returns:
            A list of tuples, each containing the indices of overlapping polygons.

        Notes:
            This function serves also as an example of how to implement additional geometry checks.
        """
        logger.info("Finding overlapping polygons in the GeoDataFrame...")

        poly_gdf = self.gdf[self.gdf.geom_type.isin(["Polygon", "MultiPolygon"])]
        if poly_gdf.empty:
            return []

        # Reset index to align with spatial index
        poly_reset = poly_gdf.reset_index()
        original_indices = poly_reset["index"].tolist()

        sindex = poly_reset.sindex
        overlaps = []

        for reset_idx, geometry in poly_reset[geometry_column].items():
            # Use spatial index for candidates
            possible_matches = list(sindex.intersection(geometry.bounds))
            possible_matches = [idx for idx in possible_matches if idx > reset_idx]

            for other_reset_idx in possible_matches:
                other_geometry = poly_reset.at[other_reset_idx, geometry_column]
                if geometry.intersects(other_geometry):
                    # Convert back to original indices
                    orig_idx1 = original_indices[reset_idx]
                    orig_idx2 = original_indices[other_reset_idx]
                    overlaps.extend([(orig_idx1, orig_idx2), (orig_idx2, orig_idx1)])

        return overlaps

    @staticmethod
    def _reduce_name_length(
        name: str, max_len: int = Config.POSTGRES_MAX_NAME_LENGTH
    ) -> str:
        """Reduce the length of a name to fit within the maximum allowed length.

        Args:
            name: The original name.
            max_len: The maximum allowed length.

        Returns:
            The reduced name.
        """
        h = hashlib.md5(name.encode()).hexdigest()[: Config.HASH_HEX_LENGTH]
        name = f"{name[:max_len-Config.HASH_SUFFIX_LENGTH]}_{h}"

        return name

    @staticmethod
    def _harmonize_name_gdf(
        name: str, max_len: int = Config.POSTGRES_MAX_NAME_LENGTH
    ) -> str:
        """
        Harmonize a gdf name to be compatible with database naming conventions.

        Args:
            name: Original gdf name.
            max_len: Maximum length for the name.

        Returns:
            A harmonized gdf name.
        """
        if name.strip() == "":
            error_msg = f"Name must not be empty or whitespace. Received: '{name}'"
            handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)

        clean_name = re.sub(
            NamingPatterns.PATTERN_GDF_NAME.value, "_", name.lower()
        ).strip("_")

        if len(clean_name) > max_len:
            clean_name = GeoprocessingVector._reduce_name_length(
                name=clean_name, max_len=max_len
            )

        return clean_name

    def _rename_gdf_columns(self):
        """Rename GeoDataFrame columns based on ColumnMappings."""
        logger.info("Renaming GeoDataFrame columns based on ColumnMappings...")

        self.gdf.columns = self.gdf.columns.str.lower()
        self.gdf.columns = self.gdf.columns.str.replace(" ", "_", regex=False)
        self.gdf.columns = self.gdf.columns.str.replace("-", "_", regex=False)

        rename_map: dict = {}

        for col in list(self.gdf.columns):
            norm = col.strip().lower()

            mapping = ColumnMappings.find(norm)
            if mapping:
                new_name = mapping.value.canonical
            else:
                new_name = norm

            if new_name != col:
                rename_map[col] = new_name

        if rename_map:
            self.gdf = self.gdf.rename(columns=rename_map)

    def _handle_null_values_in_attributes(self):
        """Handle null values in GeoDataFrame attributes based on AttributeNullValues."""
        mapping: dict = {}
        for member in AttributeNullValues:
            value = member.value
            if isinstance(value, str) or value is None:
                mapping[value] = None
        self.gdf = self.gdf.replace(mapping)

    @staticmethod
    def _read_csv_as_gdf(vector_file: Path) -> gpd.GeoDataFrame:
        """
        Read a spatial CSV file and return a GeoDataFrame.

        This function:
        - Tries to read the CSV with UTF-8, falls back to Latin-1 if decoding fails.
        - Normalizes column names to lowercase.
        - Detects coordinate columns (x/y or lon/lat) using ColumnMappings.
        - Looks up CRS from CSVDataRegistryForSourceCRS if available.

        Args:
            vector_file: Path to the CSV file.

        Returns:
            A GeoDataFrame constructed from the CSV.
        """
        try:
            df = read_csv_file(vector_file=vector_file)

            # Normalize column names
            df.columns = df.columns.str.lower()

            # Identify coordinate columns
            x_col = set(
                ColumnMappings.LONGITUDE.value.alias
                + [ColumnMappings.LONGITUDE.value.canonical]
            ).intersection(df.columns)
            y_col = set(
                ColumnMappings.LATITUDE.value.alias
                + [ColumnMappings.LATITUDE.value.canonical]
            ).intersection(df.columns)

            # Determine CRS from registry (if defined)
            source_crs = (
                CSVDataRegistryForSourceCRS[vector_file.stem.lower()].value[1]
                if vector_file.stem.lower() in CSVDataRegistryForSourceCRS.__members__
                else None
            )

            # Validate geometry columns
            if not x_col or not y_col:
                raise ValueError(
                    f"CSV file does not contain valid geometry columns: {vector_file}"
                )

            # Create GeoDataFrame
            gdf = gpd.GeoDataFrame(
                df,
                geometry=gpd.points_from_xy(df[list(x_col)[0]], df[list(y_col)[0]]),
                crs=source_crs if source_crs else "EPSG:4326",
            )
            return gdf

        except Exception as e:
            logger.error(f"Failed to read CSV {vector_file}: {e}")
            raise

    def validate_vector_data(self):
        """Validate the input GeoDataFrame or regular DataFrame for vector data processing."""
        logger.info("Validating input data for vector processing...")

        # --- CASE 1: Non-spatial pandas DataFrame ---
        if not isinstance(self.gdf, gpd.GeoDataFrame):

            if isinstance(self.gdf, pd.DataFrame):
                logger.info(
                    "Input is a regular DataFrame. Skipping geometry/CRS checks."
                )

                # No geometry → Just reset index and accept
                self.gdf = self.gdf.reset_index(drop=True)
                logger.info("Input DataFrame passed validation.")
                return
            else:
                error_msg = "Input must be a GeoDataFrame or a pandas DataFrame."
                handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)

        # --- CASE 2: GeoDataFrame present ---
        logger.info("Input is a GeoDataFrame. Checking geometry and CRS...")

        # If GeoDataFrame but geometry missing
        if not hasattr(self.gdf, "geometry") or "geometry" not in self.gdf.columns:
            logger.warning(
                "GeoDataFrame has no geometry column. Treating as non-spatial table."
            )
            self.gdf = pd.DataFrame(self.gdf).reset_index(drop=True)
            return

        # Empty GeoDataFrame
        if self.gdf.empty:
            logger.warning("GeoDataFrame is empty. Proceeding with empty dataset.")
            return

        # CRS checks
        if self.gdf.crs is None:
            error_msg = "GeoDataFrame must have a CRS before processing."
            handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)

        try:
            epsg_code = self.gdf.crs.to_epsg()
            if epsg_code is None:
                error_msg = "GeoDataFrame CRS is invalid or not EPSG compatible."
                handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)
        except Exception:
            error_msg = "GeoDataFrame CRS is invalid or unreadable."
            handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)

        # Final cleanup
        self.gdf = self.gdf.reset_index(drop=True)
        logger.info("Input GeoDataFrame passed validation.")

    def harmonize_gdf(
        self,
        expected_types: dict = None,
        drop_duplicates: bool = True,
        drop_null_geoms: bool = True,
        rename_columns: bool = True,
    ) -> gpd.GeoDataFrame:
        """Harmonise a GeoDataFrame using different methods.

        Args:
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
        logger.info("Starting GeoDataFrame harmonization process...")

        if any(
            [
                not isinstance(self.gdf, gpd.GeoDataFrame),
                self.gdf.geometry.name not in self.gdf.columns,
            ]
        ):
            error_msg = "Input must be a valid GeoDataFrame with a geometry column."
            handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)

        # Remove duplicate rows
        if drop_duplicates:
            self.gdf = self.gdf.drop_duplicates()

        # Drop null geometries and copy BEFORE any assignment to columns
        if drop_null_geoms and self.gdf.geometry.isnull().any():
            self.gdf = self.gdf[~self.gdf.geometry.isnull()].copy()

        # Rename columns based on mapping
        if rename_columns:
            self._rename_gdf_columns()

        # Handle null values in attributes
        self._handle_null_values_in_attributes()

        # Cast columns to expected types if provided
        if expected_types:
            for col, typ in expected_types.items():
                if col in self.gdf.columns:
                    self.gdf[col] = self.gdf[col].astype(typ)

        logger.info("GeoDataFrame harmonization completed.")

    def clean_geometries_gdf(
        self,
        is_fix_invalid: bool = True,
        is_check_overlaps: bool = False,
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
            error_msg = "Input must be a valid GeoDataFrame with a geometry column."
            handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)

        geometry_column = self.gdf.geometry.name

        # Fix invalid geometries if requested
        if is_fix_invalid:
            logger.info("Fixing invalid geometries...")
            if geometry_column not in self.gdf.columns:
                error_msg = f"GeoDataFrame must contain a geometry column named '{geometry_column}'."
                handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)

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
            overlaps = self._find_overlapping_polygons(geometry_column)
            if overlaps:
                logger.warning(f"Overlapping polygons detected: {overlaps}")

        # Other error cases for geometries can be added here, such as self-intersections, etc.
        logger.info("Geometry cleaning process completed.")

    def harmonize_crs_gdf(self) -> gpd.GeoDataFrame:
        """Harmonise the CRS (Coordinate Reference System) of a GeoDataFrame."""
        logger.info("Starting CRS harmonization process...")

        if not isinstance(self.gdf, gpd.GeoDataFrame):
            error_msg = "Input must be a GeoDataFrame."
            handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)

        # Ensure the geometry column is set to the correct CRS
        if not self.gdf.crs:
            error_msg = "GeoDataFrame must have a CRS set before harmonizing."
            handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)

        # Reproject the GeoDataFrame to the target CRS if it is different
        if (
            self.gdf.crs.to_string() != str(self.target_crs)
            and self.gdf.crs.to_epsg() != self.target_crs
        ):
            self.gdf = self.gdf.to_crs(self.target_crs)

    @staticmethod
    def convert_vector_files_to_gdf(vector_files: list[Path]) -> list[gpd.GeoDataFrame]:
        """Convert a list of vector file paths to multiple GeoDataFrames.

        Args:
            vector_files: The list of vector file paths to convert.

        Returns:
            The resulting GeoDataFrames.
        """
        logger.info(f"Converting {len(vector_files)} vector files to GeoDataFrame...")

        vector_data_gdf_list = []
        for vector_file in vector_files:
            if not vector_file.exists():
                error_msg = f"Vector file does not exist: {vector_file}"
                handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)

            try:
                if vector_file.suffix.lower() == ".csv":
                    # Special CSV file reading
                    gdf = GeoprocessingVector._read_csv_as_gdf(vector_file)
                    gdf_name = vector_file.stem
                    clean_name = GeoprocessingVector._harmonize_name_gdf(name=gdf_name)

                    vector_data_gdf_list.append((clean_name, gdf))

                else:
                    # Standard vector file reading
                    layers = fiona.listlayers(vector_file)
                    for layer in layers:
                        gdf = gpd.read_file(vector_file, layer=layer)
                        if len(layers) == 1:
                            gdf_name = vector_file.stem
                        else:
                            gdf_name = f"{vector_file.stem}_{layer.strip()}"

                        clean_name = GeoprocessingVector._harmonize_name_gdf(
                            name=gdf_name
                        )

                        vector_data_gdf_list.append((clean_name, gdf))
            except Exception as e:
                logger.warning(
                    f"Error reading vector file {vector_file}, skipping: {e}"
                )
                continue

        return vector_data_gdf_list


def geoprocessing_vector_data(
    gdf_list: list[tuple[str, gpd.GeoDataFrame]],
    collection_id: str,
    target_crs: str = Config.GLOBAL_CRS,
):
    """Process vector data and insert into PostGIS and Vector API.

    Args:
        gdf_list: List of tuples containing table names and GeoDataFrames to process.
        target_crs: Target CRS as an EPSG code (e.g., 4326).
        collection_id: Unique ID for the Vector collection.
    """
    add_process_to_logger(logger, "Processing Vector Data PostGIS")

    if not gdf_list:
        error_msg = "gdf_list must be a non-empty list of (table, gdf) tuples."
        handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)

    logger.info(f"Found {len(gdf_list)} vector tables to process.")

    # Iterate over each table and its corresponding GeoDataFrame
    for table, gdf in gdf_list:
        logger.info(f"Processing vector data for table: {table}")

        # Create an instance of GeoprocessingVector
        processor = GeoprocessingVector(
            gdf=gdf,
            target_crs=target_crs,
            collection_id=collection_id,
        )

        geometry_col = set(
            ColumnMappings.GEOMETRY.value.alias
            + [ColumnMappings.GEOMETRY.value.canonical]
        ).intersection(gdf.columns)

        if geometry_col:
            logger.info(f"Table {table} is spatial. Processing geometry steps.")

            logger.info(
                f"Loaded GeoDataFrame: {len(processor.gdf)} rows, columns={list(processor.gdf.columns)}"
            )
            processor.validate_vector_data()
            processor.harmonize_gdf()
            processor.clean_geometries_gdf()
            processor.harmonize_crs_gdf()

            # Get the processed GeoDataFrame
            processed_gdf = processor.gdf
            logger.info(f"Vector data for table {table} processed successfully.")

            # Check if processed_gdf is empty before proceeding
            if processed_gdf is None or processed_gdf.empty:
                logger.warning(
                    f"Skipping postgis and parquet export because GeoDataFrame is empty for table '{table}'."
                )
                return

            # Insert processed GeoDataFrame into PostGIS
            with PostGISManager() as pg_manager:
                pg_manager.insert_table_data(
                    gdf=processed_gdf,
                    table_name=table,
                )

            # Insert processed GeoDataFrame into GeoParquet
            DuckDBManager.save_gdf_to_geoparquet(
                gdf=processed_gdf, output_file_name=table
            )

        # Fallback non-spatial table handling
        if not geometry_col:
            logger.warning(
                f"Table {table} is non-spatial. Skipping geometry processing steps."
            )
            processor._rename_gdf_columns()

            logger.info(f"Non-spatial data for table {table} processed successfully.")
            processed_gdf = processor.gdf

            if processed_gdf is None or processed_gdf.empty:
                logger.warning(
                    f"Skipping parquet export because GeoDataFrame is empty for table '{table}'."
                )
                return

            # Insert processed GeoDataFrame into PostGIS
            with PostGISManager() as pg_manager:
                pg_manager.insert_table_data(
                    gdf=processed_gdf,
                    table_name=table,
                )

            # Insert processed GeoDataFrame into GeoParquet
            DuckDBManager.save_df_to_parquet(df=processed_gdf, output_file_name=table)


class GeoprocessingRaster:
    def __init__(self, config: Config, raster_paths: list[Path] | Path):
        self.config = config

        # Ensure raster_paths is a list of Path objects
        if isinstance(raster_paths, Path):
            raster_paths = [raster_paths]
        self.raster_paths = [Path(p) for p in raster_paths]

        self.rasters = self._open_rasters()

        self.raster_metadata = {}
        self._analyze_and_store_metadata()
        self.harmonized_name = None

    def _open_rasters(self) -> dict[Path, rasterio.io.DatasetReader]:
        """Open raster files using rasterio and validate them.

        Returns:
            List of opened rasterio DatasetReader objects.
        """
        logger.info("Opening raster files...")

        if not self.raster_paths:
            error_msg = "No raster files provided."
            handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)

        rasters = {}
        for raster_path in self.raster_paths:
            logger.debug(f"Opening and validating raster: {raster_path}")
            try:
                with rasterio.open(raster_path) as src:
                    if src.crs is None:
                        error_msg = f"CRS is not defined: {raster_path}"
                        handle_error(
                            logger=logger, error_msg=error_msg, exc_class=ValueError
                        )
                    if src.count <= 0:
                        error_msg = f"Invalid band count: {raster_path}"
                        handle_error(
                            logger=logger, error_msg=error_msg, exc_class=ValueError
                        )

                    opened_raster = rasterio.open(raster_path)
                    rasters[raster_path] = opened_raster
                    logger.debug(
                        f"Raster {raster_path} opened and validated successfully."
                    )
            except Exception as e:
                for src in rasters.values():
                    src.close()

                logger.exception(f"Error opening raster: {raster_path}")

                if isinstance(e, ValueError):
                    raise
                else:
                    error_msg = f"Error opening raster {raster_path}: {e}"
                    handle_error(
                        logger=logger, error_msg=error_msg, exc_class=RuntimeError
                    )

        logger.info(f"Opened {len(rasters)} raster files.")
        return rasters

    def _analyze_and_store_metadata(self):
        """Analyze rasters and store enriched metadata."""
        logger.info("Analyzing raster files and extracting metadata...")

        for raster_path, src in self.rasters.items():
            try:
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

                tags = dict(src.tags()) if src.tags() else {}
                datetime_value = tags.get("TIFFTAG_DATETIME", Config.DEFAULT_DATETIME)

                self.raster_metadata[raster_path] = {
                    "id": raster_path.stem,
                    "datetime": datetime_value,
                    "bbox": [bounds.left, bounds.bottom, bounds.right, bounds.top],
                    "geometry": geometry,
                    "bands": src.count,
                    "width": src.width,
                    "height": src.height,
                    "crs": str(src.crs) if src.crs else None,
                    "nodata": src.nodata,
                    "dtype": str(src.dtypes[0]) if src.dtypes else None,
                    "tags": tags,
                }

                logger.debug(f"Stored metadata for: {raster_path}")

            except Exception:
                error_msg = f"Error analyzing raster: {raster_path}"
                handle_error(logger=logger, error_msg=error_msg, exc_class=RuntimeError)

        logger.info(f"Analyzed {len(self.rasters)} raster files.")

    def _harmonize_name_for_single_raster(self, raster_name: str) -> str:
        """Harmonize a raster file name to be compatible with database naming conventions.

        Args:
            raster_name: Original raster file name.

        Returns:
            A harmonized raster file name without extension.
        """
        if not raster_name.strip():
            error_msg = "Raster file name must not be empty or whitespace."
            handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)

        input_path = Path(raster_name)
        name = input_path.stem
        extension = input_path.suffix.lower()
        max_name_length = self.config.POSTGRES_MAX_NAME_LENGTH - len(extension)

        pattern = NamingPatterns.PATTERN_RASTER_NAME.value
        clean_name = re.sub(pattern, Config.HASH_SEPARATOR, name.lower()).strip(
            Config.HASH_SEPARATOR
        )

        if len(clean_name) > max_name_length:
            h = hashlib.md5(clean_name.encode()).hexdigest()[: Config.HASH_HEX_LENGTH]
            available_length = max_name_length - (Config.HASH_SUFFIX_LENGTH)
            if available_length > 0:
                clean_name = (
                    f"{clean_name[:available_length]}{Config.HASH_SEPARATOR}{h}"
                )
            else:
                clean_name = h[:max_name_length]

        self.harmonized_name = clean_name

    def _get_cog_creation_profile(self, profile: str) -> dict:
        """Get COG creation profile with predefined options.

        Args:
            profile: Profile name ('default', 'fast', 'high_quality').

        Returns:
            Dictionary with COG creation options.

        Notes:
            - For now, we define three profiles: 'default', 'fast', and 'high_quality', but changes can be made.
        """
        if profile not in ["default", "fast", "high_quality"]:
            logger.warning(
                f"Unknown COG profile '{profile}'. Falling back to 'default' profile."
            )
            profile = "default"

        profiles = {
            "default": {
                "compress": "DEFLATE",
                "num_threads": "ALL_CPUS",
                "bigtiff": "YES",
                "overviews": "AUTO",
                "blocksize": None,
                "predictor": None,
            },
            "fast": {
                "compress": "LZW",
                "num_threads": "ALL_CPUS",
                "bigtiff": "IF_SAFER",
                "overviews": "NONE",
                "blocksize": "1024",
                "predictor": None,
            },
            "high_quality": {
                "compress": "DEFLATE",
                "num_threads": "ALL_CPUS",
                "bigtiff": "YES",
                "overviews": "AUTO",
                "blocksize": "512",
                "predictor": "2",  # For continuous data
            },
        }

        return profiles.get(profile, profiles["default"])

    def _build_gdalwarp_command(
        self,
        input_raster_path: Path,
        output_path: Path,
        target_crs: int,
        cog_profile: str,
        reference_nodata: float = None,
        overwrite_existing: bool = True,
        additional_options: list[str] = None,
    ) -> list[str]:
        """Build gdalwarp command for COG creation.

        Args:
            input_raster_path: Path to input raster file.
            output_path: Path to output COG file.
            target_crs: Target CRS as EPSG code.
            cog_profile: COG creation profile name.
            reference_nodata: NoData value to set in the output raster.
            overwrite_existing: Whether to overwrite existing files.
            additional_options: Additional gdalwarp options.

        Returns:
            List of command arguments for gdalwarp.
        """
        # Base command
        warp_cmd = [
            "gdalwarp",
            "-t_srs",
            f"EPSG:{target_crs}",
            "-of",
            "COG",
        ]

        # Overwrite option
        if overwrite_existing:
            warp_cmd.append("-overwrite")

        # COG profile
        profile = self._get_cog_creation_profile(profile=cog_profile)

        # Apply profile options
        for key, value in profile.items():
            if value is not None:
                option_name = key.upper()
                warp_cmd.extend(["-co", f"{option_name}={value}"])

        # Processing options
        warp_cmd.extend(["-multi", "-dstalpha"])

        # NoData value
        if reference_nodata is not None:
            warp_cmd.extend(["-dstnodata", str(reference_nodata)])

        # Additional custom options
        if additional_options:
            warp_cmd.extend(additional_options)

        # Input and output files
        warp_cmd.extend([str(input_raster_path), str(output_path)])

        return warp_cmd

    def _restore_backup_file(self, backup_file: Path, restore_path: Path):
        """Restore a backup file in case of an error.

        Args:
            backup_file: Path to the backup file.
            restore_path: Path to the output file to restore.
        """
        if not backup_file or not backup_file.exists():
            return  # Nothing to restore

        # Remove existing restore path if it exists
        if restore_path and restore_path.exists():
            try:
                restore_path.unlink()
                logger.info(f"Removed existing file before restore: {restore_path}")
            except OSError as e:
                logger.error(
                    "Failed to remove existing file %s: %s. Leaving backup in place.",
                    restore_path,
                    e,
                )
                logger.debug("Traceback for unlink failure:", exc_info=True)
                return

        # Attempt to rename backup to restore path
        try:
            backup_file.rename(restore_path)
            logger.info(f"Restored backup: {backup_file} -> {restore_path}")
        except (OSError, PermissionError) as e:
            logger.error(
                "Failed to rename backup %s to %s: %s. Backup remains in place.",
                backup_file,
                restore_path,
                e,
            )
            logger.debug("Traceback for rename failure:", exc_info=True)
        except Exception as e:
            logger.exception(
                f"Unexpected error while restoring backup {backup_file}: {e}"
            )

    def _warp_raster(self, warp_cmd: list[str], raster_path: Path, output_path: Path):
        """Warp raster to a target CRS using gdalwarp.

        Args:
            warp_cmd: List of command arguments for gdalwarp.
            raster_path: Path to the input raster file.
            output_path: Path to the output raster file.
        """
        if raster_path not in self.raster_paths:
            error_msg = f"Raster {raster_path} not registered in the class."
            handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)

        try:
            subprocess.run(warp_cmd, check=True, capture_output=True)
            logger.info(f"Raster warped successfully: {output_path}")

        except subprocess.CalledProcessError as e:
            stderr_text = (
                e.stderr.decode(errors="ignore")
                if isinstance(e.stderr, (bytes, bytearray))
                else str(e.stderr)
            )

            error_msg = (
                f"gdalwarp failed for {raster_path}: exit code {e.returncode}\n"
                f"STDERR:\n{stderr_text}"
            )

            handle_error(logger=logger, error_msg=error_msg, exc_class=RuntimeError)

    def prepare_cog_metadata_for_stac(
        self, original_raster_path: Path, cog_file_path: Path
    ) -> dict:
        """
        Extract clean, STAC-compliant metadata from a Cloud Optimized GeoTIFF (COG).

        Args:
            original_raster_path: Path to the original raster file.
            cog_file_path: Path to the COG file.

        Returns:
            dict: STAC-compliant metadata item.
        """
        if original_raster_path not in self.raster_metadata:
            handle_error(
                logger,
                f"No stored metadata for raster: {original_raster_path}",
                ValueError,
            )
        if not cog_file_path.exists():
            handle_error(
                logger, f"COG file {cog_file_path} does not exist.", FileNotFoundError
            )

        with rasterio.open(cog_file_path) as src:
            bounds = src.bounds
            crs = src.crs

            raster_bands = [
                {
                    "nodata": (src.nodatavals[i - 1] if src.nodatavals else src.nodata),
                    "data_type": str(src.dtypes[i - 1]),
                    "spatial_resolution": abs(src.transform[0]),
                }
                for i in range(1, src.count + 1)
            ]

            stored_metadata = self.raster_metadata[original_raster_path]

            try:
                raw_transform = src.transform.to_gdal()
                proj_transform = [float(x) for x in raw_transform]
            except Exception:
                proj_transform = (
                    list(map(float, src.transform))
                    if hasattr(src.transform, "__iter__")
                    else []
                )

            dt_val = stored_metadata.get("datetime", Config.DEFAULT_DATETIME)
            if hasattr(dt_val, "isoformat"):
                dt_val = dt_val.isoformat()

            # Return a plain dict (compatible with other gis_pipeline code / tests)
            assets = {
                "cog": {
                    "href": f"file://{cog_file_path.absolute()}",
                    "type": "image/tiff; application=geotiff; profile=cloud-optimized",
                    "roles": ["data"],
                    "title": cog_file_path.name,
                    "raster_bands": raster_bands,
                }
            }

            return {
                "id": cog_file_path.stem,
                "geometry": {
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
                },
                "bbox": [bounds.left, bounds.bottom, bounds.right, bounds.top],
                "datetime": dt_val,
                "properties": {
                    "datetime": dt_val,
                    "proj:epsg": crs.to_epsg() if crs else 4326,
                    "proj:shape": [src.height, src.width],
                    "proj:transform": proj_transform,
                    "raster:bands": raster_bands,
                    "bands": src.count,
                    "source": "cog_processing",
                    "data_type": "raster",
                },
                "assets": assets,
                "stac_extensions": [
                    "https://stac-extensions.github.io/raster/v1.1.0/schema.json",
                    "https://stac-extensions.github.io/projection/v1.1.0/schema.json",
                ],
                "file_url": f"file://{cog_file_path.absolute()}",
            }

    def process_raster_to_cog(
        self,
        output_path: Path,
        target_crs: int,
        reference_nodata: float = None,
        overwrite_existing: bool = True,
    ) -> list[tuple[Path, Path]]:
        """Harmonize rasters and save to cog format.

        Args:
            output_dir: Directory where the harmonized raster will be saved.
            crs: Target CRS to harmonize to. Default is project CRS.
            reference_nodata: NoData value to set in the output raster.
            overwrite_existing: Whether to overwrite existing files. Default is True.

        Returns:
            List of tuples (original_raster_path, cog_file_path).
        """
        if target_crs is None:
            target_crs = self.config.GLOBAL_CRS

        harmonized_files = []
        processing_errors = []

        for raster_path in self.raster_paths:
            backup_file = None

            if hasattr(self, "_harmonize_name_for_single_raster"):
                self._harmonize_name_for_single_raster(raster_name=raster_path.name)
            harmonized_names = getattr(self, "harmonized_name", raster_path.stem)
            output_cog = output_path / f"{harmonized_names}_cog.tif"

            if output_cog.exists() and not overwrite_existing:
                timestamp = int(time.time())
                backup_file = output_cog.with_name(
                    f"{output_cog.stem}_old_{timestamp}{output_cog.suffix}"
                )
                logger.info(f"Creating backup of existing file: {backup_file}")
                output_cog.rename(backup_file)
            elif output_cog.exists():
                logger.info(f"Overwriting existing file: {output_cog}")
            try:
                warp_cmd = self._build_gdalwarp_command(
                    input_raster_path=raster_path,
                    output_path=output_cog,
                    target_crs=target_crs,
                    cog_profile="default",
                    reference_nodata=reference_nodata,
                    overwrite_existing=overwrite_existing,
                )

                # Execute the gdalwarp command
                self._warp_raster(
                    warp_cmd=warp_cmd, raster_path=raster_path, output_path=output_cog
                )

                # Verify output file was created
                if not output_cog.exists():
                    error_msg = f"COG file was not created: {output_cog}"
                    handle_error(
                        logger=logger, error_msg=error_msg, exc_class=RuntimeError
                    )

                harmonized_files.append((raster_path, output_cog))
                logger.info(f"Harmonized raster saved: {output_cog}")

                # Cleanup backup if everything went well
                if backup_file and backup_file.exists():
                    backup_file.unlink()
                    logger.debug(f"Backup removed: {backup_file}")

            except subprocess.CalledProcessError as e:
                error_msg = (
                    f"gdalwarp failed for {raster_path}: exit code {e.returncode}"
                )
                logger.error(error_msg)
                logger.error(f"STDERR:\n{e.stderr}")
                processing_errors.append(error_msg)

                # Restore backup if something went wrong
                self._restore_backup_file(backup_file, output_path)

            except Exception as e:
                error_msg = f"Unexpected error processing {raster_path}: {e}"
                logger.error(error_msg, exc_info=True)
                processing_errors.append(error_msg)

                # Restore backup if something went wrong
                self._restore_backup_file(backup_file, output_path)

        if processing_errors and not harmonized_files:
            error_msg = "All raster processing failed."
            handle_error(
                logger=logger,
                error_msg=f"{error_msg} Errors:\n" + "\n".join(processing_errors),
                exc_class=RuntimeError,
            )
        elif processing_errors:
            logger.warning(
                f"Some rasters failed to process: {len(processing_errors)} errors"
            )

        return harmonized_files

    def close_all_rasters(self):
        """Close all opened raster files."""
        errors = []

        for raster in self.rasters.values():
            try:
                raster.close()
                logger.debug(f"Closed raster file: {raster.name}")
            except Exception as e:
                error_msg = f"Failed to close raster {raster.name}: {e}"
                logger.error(error_msg)
                errors.append(error_msg)

        if errors:
            logger.warning(f"Some rasters failed to close: {len(errors)} errors")

        logger.info("All raster files have been closed.")


def geoprocessing_raster_data(
    rasters: list[Path],
    target_crs: int,
    stac_collection_id: str,
    api_url: str,
    output_dir: Path | str = Config.RASTER_COG_PATH,
):
    """Process raster data by harmonizing, creating COGs, extracting metadata, saving in postgis and posting to STAC API.

    Args:
        rasters: List of raster file paths to process.
        target_crs: Target CRS as EPSG code (e.g., 4326).
        stac_collection_id: Unique ID for the STAC collection.
        api_url: URL of the STAC API.
        output_dir: Directory to save the harmonized COG files.
    """
    add_process_to_logger(logger, "Processing Raster Data PostGIS")
    output_dir = Path(output_dir)

    if not rasters:
        error_msg = "No raster files found in the specified directory."
        handle_error(logger=logger, error_msg=error_msg, exc_class=RuntimeError)

    processing = GeoprocessingRaster(config=Config, raster_paths=rasters)

    # Harmonize raster data
    logger.info(f"Found {len(rasters)} raster files to process.")
    harmonized_cog_pairs = processing.process_raster_to_cog(
        output_path=output_dir,
        target_crs=target_crs,
    )

    logger.info(f"Found {len(harmonized_cog_pairs)} harmonized raster files:")
    for original_raster, cog_file in harmonized_cog_pairs:
        logger.info(f"  - {cog_file.name} (from {original_raster.name})")

    if not harmonized_cog_pairs:
        error_msg = "No harmonized COG files were created successfully"
        handle_error(logger=logger, error_msg=error_msg, exc_class=RuntimeError)

    all_raster_metadata = []

    # Process each harmonized COG to extract metadata and prepare for STAC
    for original_raster, cog_file in harmonized_cog_pairs:
        logger.info(f"Processing COG file: {cog_file}")

        try:
            # Verify COG file exists
            if not cog_file.exists():
                error_msg = f"COG file does not exist: {cog_file}"
                handle_error(logger=logger, error_msg=error_msg, exc_class=RuntimeError)

            # Extract metadata using optimized class
            metadata = processing.prepare_cog_metadata_for_stac(
                original_raster_path=original_raster, cog_file_path=cog_file
            )

            # Insert metadata into PostGIS
            with PostGISManager() as pg_manager:
                pg_manager.insert_cog_metadata(metadata=metadata, table_name="cogs")

            all_raster_metadata.append(metadata)
            logger.info(f"Prepared metadata for: {cog_file.name}")

        except Exception as e:
            logger.warning(f"Error processing COG {cog_file}: {e}", exc_info=True)
            continue

    if not all_raster_metadata:
        error_msg = f"No valid metadata was extracted from {len(rasters)} raster(s)."
        handle_error(logger=logger, error_msg=error_msg, exc_class=RuntimeError)

    logger.info(f"Creating STAC items from {len(all_raster_metadata)} metadata entries")

    # Build STAC items from raster metadata
    item_raster_list = build_stac_items_from_cog(
        raster_metadata_list=all_raster_metadata, source_name="cog_processing"
    )

    # Build STAC collection from items
    stac_collection = build_stac_collection_from_items(
        items=item_raster_list,
        collection_id=stac_collection_id,
    )

    # Create a STAC API client
    stac_client = StacApiClient(
        api_url=api_url,
        collection_id=stac_collection_id,
        stac_collection=stac_collection,
        stac_items=item_raster_list,
        logger=logger,
    )

    # Post the collection to the STAC API
    stac_client.post_collection()

    # PUT (update) items to the STAC API
    stac_client.upsert_items()

    # Close all opened rasters
    processing.close_all_rasters()
